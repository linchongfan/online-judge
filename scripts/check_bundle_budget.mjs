// Bundle budget gate: run after `vite build`.
// The workspace page lazy-loads Monaco, which is large but only fetched when
// the user opens the editor. The initial shell must stay small.
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ASSETS = 'dist/assets'
const INITIAL_BUDGET = 1_600_000 // bytes, index-*.js
const CHUNK_BUDGET = 4_000_000 // bytes, any single lazy chunk
const TOTAL_BUDGET = 8_000_000 // bytes, all JS

const files = readdirSync(ASSETS).filter((name) => name.endsWith('.js'))
if (!files.length) {
  console.error('bundle budget: no JS assets found; run `bun run build` first')
  process.exit(1)
}

let total = 0
const oversized = []
for (const name of files) {
  const size = statSync(join(ASSETS, name)).size
  total += size
  if (/^index-.*\.js$/.test(name) && size > INITIAL_BUDGET) {
    oversized.push(`${name} ${size} > initial budget ${INITIAL_BUDGET}`)
  }
  if (size > CHUNK_BUDGET) {
    oversized.push(`${name} ${size} > chunk budget ${CHUNK_BUDGET}`)
  }
}

const entry = files.find((name) => /^index-.*\.js$/.test(name))
if (!entry) {
  console.error('bundle budget: no initial index-*.js chunk found')
  process.exit(1)
}

if (total > TOTAL_BUDGET) {
  oversized.push(`total JS ${total} > budget ${TOTAL_BUDGET}`)
}

console.log(`bundle budget: ${files.length} chunks, total ${total} bytes, entry ${entry}`)
if (oversized.length) {
  for (const issue of oversized) console.error(`  OVER BUDGET: ${issue}`)
  process.exit(1)
}
