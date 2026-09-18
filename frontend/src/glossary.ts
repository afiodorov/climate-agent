/** Term definitions, fetched once per page load and shared by every answer.
 *
 *  The server owns the words and the definitions (`/api/glossary`, numbers
 *  rendered from the data, English plus translations). This module turns them
 *  into a matcher and a rehype plugin that wraps each mention in the rendered
 *  markdown in an `<abbr data-term>` for the Term component to hang a tooltip
 *  on. Every language's aliases are matched at once; which language the
 *  tooltip speaks is decided per answer, by which aliases it hit. Until the
 *  fetch lands, answers render unmarked — the glossary is a courtesy, never a
 *  dependency. */

import { useEffect, useState } from 'react'
import { fetchGlossary } from './api'
import type { GlossaryEntry } from './types'

export const ENGLISH = 'en'

export interface Glossary {
  entries: GlossaryEntry[]
  /** Global, case-insensitive; alternation ordered longest-first so
   *  "evenness factor" wins over "evenness". */
  regex: RegExp
  /** Normalised alias -> entry. */
  lookup(text: string): GlossaryEntry | undefined
  /** The language an answer's mentions point to: each matched alias votes for
   *  the languages it is a spelling in, split evenly when it is one in
   *  several ("composite" is English, French and Portuguese). Ties, and text
   *  with no mention, are English. */
  language(text: string): string
}

const EMPTY: Glossary = {
  entries: [],
  regex: /$^/g,
  lookup: () => undefined,
  language: () => ENGLISH,
}

function normalise(s: string): string {
  return s.toLowerCase().replace(/[\s-]+/g, ' ')
}

function escape(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Han, kana and hangul run words together, or glue particles straight onto a
 *  noun, so a mention has no edge to anchor a word boundary on. */
const UNSPACED = /[\p{sc=Han}\p{sc=Hiragana}\p{sc=Katakana}\p{sc=Hangul}]/u

interface Alias {
  entry: GlossaryEntry
  langs: string[]
}

export function build(entries: GlossaryEntry[]): Glossary {
  const byAlias = new Map<string, Alias>()
  const bounded: string[] = []
  const unbounded: string[] = []
  const add = (alias: string, entry: GlossaryEntry, lang: string) => {
    const key = normalise(alias)
    const known = byAlias.get(key)
    if (known) {
      if (known.entry === entry && !known.langs.includes(lang)) known.langs.push(lang)
      return
    }
    byAlias.set(key, { entry, langs: [lang] })
    if (UNSPACED.test(alias)) {
      unbounded.push(escape(alias))
    } else {
      // Spaces and hyphens in an alias match either, so "dew-point" and
      // "dew point" are one spelling; a trailing s catches the plural.
      bounded.push(escape(alias).replace(/[\s-]+/g, '[\\s-]+') + 's?')
    }
  }
  for (const e of entries) {
    for (const alias of e.aliases) add(alias, e, ENGLISH)
    for (const [lang, t] of Object.entries(e.translations)) {
      for (const alias of t.aliases) add(alias, e, lang)
    }
  }
  if (byAlias.size === 0) return EMPTY
  const longest = (a: string, b: string) => b.length - a.length
  bounded.sort(longest)
  unbounded.sort(longest)
  // Word boundaries by hand: \b misbehaves around "PM2.5" and "°C".
  const parts = [
    `(?<![\\p{L}\\p{N}_])(?:${bounded.join('|')})(?![\\p{L}\\p{N}_])`,
  ]
  if (unbounded.length > 0) parts.push(`(?:${unbounded.join('|')})`)
  const regex = new RegExp(parts.join('|'), 'giu')
  const find = (text: string): Alias | undefined =>
    byAlias.get(normalise(text)) ??
    byAlias.get(normalise(text).replace(/s$/, ''))
  return {
    entries,
    regex,
    lookup: (text) => find(text)?.entry,
    language: (text) => {
      const votes = new Map<string, number>([[ENGLISH, 0]])
      // Code spans are column names and SQL, in no language.
      const prose = text.replace(/```[\s\S]*?```|`[^`\n]*`/g, ' ')
      regex.lastIndex = 0
      for (const m of prose.matchAll(regex)) {
        const hit = find(m[0])
        if (!hit) continue
        for (const lang of hit.langs) {
          votes.set(lang, (votes.get(lang) ?? 0) + 1 / hit.langs.length)
        }
      }
      let best = ENGLISH
      for (const [lang, n] of votes) if (n > (votes.get(best) ?? 0)) best = lang
      return best
    },
  }
}

let cached: Glossary | null = null
let inflight: Promise<Glossary> | null = null

function load(): Promise<Glossary> {
  if (cached) return Promise.resolve(cached)
  inflight ??= fetchGlossary()
    .then(build, () => EMPTY)
    .then((g) => (cached = g))
  return inflight
}

/** The glossary, or the empty one until it has loaded. */
export function useGlossary(): Glossary {
  const [glossary, setGlossary] = useState<Glossary>(cached ?? EMPTY)
  useEffect(() => {
    let live = true
    load().then((g) => live && setGlossary(g))
    return () => {
      live = false
    }
  }, [])
  return glossary
}

// --- The markdown side ------------------------------------------------------

// The slice of hast this plugin touches. Declared locally rather than imported
// from `hast` so the app does not depend on a transitive package's types.
interface TextNode {
  type: 'text'
  value: string
}
interface ElementNode {
  type: 'element'
  tagName: string
  properties: Record<string, unknown>
  children: Node[]
}
interface ParentNode {
  type: string
  children: Node[]
}
type Node = TextNode | ElementNode | ParentNode

// Inside these a match is a token, not a mention: code is SQL, a link's text
// is somebody else's words, and an abbr is already marked.
const SKIP = new Set(['code', 'pre', 'a', 'abbr'])

function isParent(n: Node): n is ParentNode | ElementNode {
  return 'children' in n && Array.isArray(n.children)
}

function split(value: string, regex: RegExp): Node[] {
  const out: Node[] = []
  let last = 0
  regex.lastIndex = 0
  for (const m of value.matchAll(regex)) {
    const start = m.index
    if (start > last) out.push({ type: 'text', value: value.slice(last, start) })
    out.push({
      type: 'element',
      tagName: 'abbr',
      properties: { dataTerm: m[0] },
      children: [{ type: 'text', value: m[0] }],
    })
    last = start + m[0].length
  }
  if (out.length === 0) return [{ type: 'text', value }]
  if (last < value.length) out.push({ type: 'text', value: value.slice(last) })
  return out
}

function walk(node: Node, regex: RegExp): void {
  if (!isParent(node)) return
  if (node.type === 'element' && SKIP.has((node as ElementNode).tagName)) return
  node.children = node.children.flatMap((child) => {
    if (child.type === 'text') return split((child as TextNode).value, regex)
    walk(child, regex)
    return [child]
  })
}

/** A rehype plugin wrapping every glossary mention in `<abbr data-term>`. */
export function rehypeTerms(glossary: Glossary) {
  return () => (tree: Node) => {
    if (glossary.entries.length === 0) return
    walk(tree, glossary.regex)
  }
}

/** The same marking for a plain string (the caveats are not markdown). Returns
 *  alternating text and matched-term segments for the caller to render. */
export function segments(
  text: string,
  glossary: Glossary,
): { text: string; term: boolean }[] {
  if (glossary.entries.length === 0) return [{ text, term: false }]
  return split(text, glossary.regex).map((n) =>
    n.type === 'text'
      ? { text: (n as TextNode).value, term: false }
      : { text: ((n as ElementNode).children[0] as TextNode).value, term: true },
  )
}
