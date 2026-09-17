/** Term definitions, fetched once per page load and shared by every answer.
 *
 *  The server owns the words and the definitions (`/api/glossary`, numbers
 *  rendered from the data). This module turns them into a matcher and a
 *  rehype plugin that wraps each mention in the rendered markdown in an
 *  `<abbr data-term>` for the Term component to hang a tooltip on. Until the
 *  fetch lands, answers render unmarked — the glossary is a courtesy, never a
 *  dependency. */

import { useEffect, useState } from 'react'
import { fetchGlossary } from './api'
import type { GlossaryEntry } from './types'

export interface Glossary {
  entries: GlossaryEntry[]
  /** Global, case-insensitive; alternation ordered longest-first so
   *  "evenness factor" wins over "evenness". */
  regex: RegExp
  /** Normalised alias -> entry. */
  lookup(text: string): GlossaryEntry | undefined
}

const EMPTY: Glossary = {
  entries: [],
  regex: /$^/g,
  lookup: () => undefined,
}

function normalise(s: string): string {
  return s.toLowerCase().replace(/[\s-]+/g, ' ')
}

function escape(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function build(entries: GlossaryEntry[]): Glossary {
  const byAlias = new Map<string, GlossaryEntry>()
  const patterns: string[] = []
  for (const e of entries) {
    for (const alias of e.aliases) {
      byAlias.set(normalise(alias), e)
      // Spaces and hyphens in an alias match either, so "dew-point" and
      // "dew point" are one spelling; a trailing s catches the plural.
      patterns.push(escape(alias).replace(/[\s-]+/g, '[\\s-]+') + 's?')
    }
  }
  if (patterns.length === 0) return EMPTY
  patterns.sort((a, b) => b.length - a.length)
  // Word boundaries by hand: \b misbehaves around "PM2.5" and "°C".
  const regex = new RegExp(
    `(?<![\\p{L}\\p{N}_])(?:${patterns.join('|')})(?![\\p{L}\\p{N}_])`,
    'giu',
  )
  return {
    entries,
    regex,
    lookup: (text) =>
      byAlias.get(normalise(text)) ??
      byAlias.get(normalise(text).replace(/s$/, '')),
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
