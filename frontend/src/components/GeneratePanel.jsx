import { useMemo, useRef, useState } from 'react'

const CATEGORY_ORDER = ['Amber Monsters', 'Wublins', 'Celestials']

export default function GeneratePanel({ boxMonsters, boxById, targets, onSetQty }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [focusIdx, setFocusIdx] = useState(0)
  const inputRef = useRef(null)

  // Flat, filtered, sorted-by-category list. We keep a flat order so keyboard
  // navigation lines up with what's rendered (headers don't count).
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const matches = boxMonsters.filter(
      (b) => !q || (b.display_name || b.common_name).toLowerCase().includes(q) || String(b.id).includes(q)
    )
    matches.sort((a, b) => {
      const ai = CATEGORY_ORDER.indexOf(a.category)
      const bi = CATEGORY_ORDER.indexOf(b.category)
      if (ai !== bi) return ai - bi
      return (a.display_name || a.common_name).localeCompare(b.display_name || b.common_name)
    })
    return matches.slice(0, q ? 60 : 200)
  }, [query, boxMonsters])

  // Group the visible items by category, preserving the flat order.
  const grouped = useMemo(() => {
    const groups = []
    let current = null
    filtered.forEach((b, idx) => {
      if (!current || current.category !== b.category) {
        current = { category: b.category, items: [] }
        groups.push(current)
      }
      current.items.push({ ...b, _flatIdx: idx })
    })
    return groups
  }, [filtered])

  const selected = useMemo(() => {
    return Object.entries(targets)
      .map(([id, qty]) => ({ id: Number(id), qty: Number(qty), box: boxById[Number(id)] }))
      .filter((row) => row.box)
      .sort((a, b) =>
        (a.box.display_name || a.box.common_name).localeCompare(
          b.box.display_name || b.box.common_name
        )
      )
  }, [targets, boxById])

  function toggleMonster(box) {
    const current = targets[String(box.id)] || 0
    onSetQty(box.id, current > 0 ? 0 : 1)
    setQuery('')
    setOpen(true)
    setFocusIdx(0)
    inputRef.current?.focus()
  }

  function onKeyDown(e) {
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setFocusIdx((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setFocusIdx((i) => Math.max(0, i - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const pick = filtered[focusIdx]
      if (pick) toggleMonster(pick)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div>
        <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Box monsters
        </h2>

        <div className="relative">
          <input
            ref={inputRef}
            type="text"
            placeholder="Search box monsters (e.g. Wubbox, Gnarls)…"
            value={query}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            onChange={(e) => {
              setQuery(e.target.value)
              setOpen(true)
              setFocusIdx(0)
            }}
            onKeyDown={onKeyDown}
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          {open && filtered.length > 0 && (
            <ul className="absolute z-10 mt-1 max-h-80 w-full overflow-auto rounded-md border border-slate-200 bg-white shadow-lg">
              {grouped.map((group) => (
                <li key={group.category}>
                  <div className="sticky top-0 bg-slate-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {group.category}
                  </div>
                  <ul>
                    {group.items.map((b) => {
                      const isSelected = (targets[String(b.id)] || 0) > 0
                      const isFocused = b._flatIdx === focusIdx
                      let rowBg
                      if (isSelected) {
                        rowBg = isFocused ? 'bg-indigo-200' : 'bg-indigo-100'
                      } else {
                        rowBg = isFocused ? 'bg-indigo-50' : 'hover:bg-slate-50'
                      }
                      return (
                        <li
                          key={b.id}
                          onMouseDown={(e) => {
                            e.preventDefault()
                            toggleMonster(b)
                          }}
                          onMouseEnter={() => setFocusIdx(b._flatIdx)}
                          className={`flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 text-sm ${rowBg}`}
                        >
                          <span className="flex min-w-0 items-center gap-2">
                            <span
                              className={
                                'inline-flex size-4 shrink-0 items-center justify-center rounded border text-[10px] leading-none ' +
                                (isSelected
                                  ? 'border-indigo-600 bg-indigo-600 text-white'
                                  : 'border-slate-300 bg-white text-transparent')
                              }
                              aria-hidden="true"
                            >
                              ✓
                            </span>
                            <span
                              className={
                                'truncate font-medium ' +
                                (isSelected ? 'text-indigo-900' : 'text-slate-800')
                              }
                            >
                              {b.display_name || b.common_name}
                            </span>
                          </span>
                          <span className="shrink-0 text-xs text-slate-500">
                            id={b.id} · {b.total_reqs} reqs ({b.unique_reqs} unique)
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-col overflow-hidden rounded-md border border-slate-200 bg-white">
        <div className="border-b border-slate-200 bg-slate-100 px-3 py-2 text-xs uppercase tracking-wide text-slate-600">
          Selected ({selected.length})
        </div>
        <div className="flex-1 overflow-y-auto">
          {selected.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-500">
              Nothing selected — search above and click a result to add.
            </div>
          ) : (
            <ul>
              {selected.map(({ id, qty, box }) => (
                <li
                  key={id}
                  className="flex items-center justify-between gap-3 border-b border-slate-100 px-3 py-2 last:border-b-0"
                >
                  <button
                    onClick={() => onSetQty(id, 0)}
                    className="rounded-full px-2 py-0.5 text-sm text-slate-400 hover:bg-red-50 hover:text-red-600"
                    title="Remove"
                  >
                    ✕
                  </button>
                  <span className="flex-1 text-sm font-medium">
                    {box.display_name || box.common_name}
                  </span>
                  <span className="w-40 text-xs text-slate-500">
                    {box.total_reqs} reqs ({box.unique_reqs} unique)
                  </span>
                  <label className="flex items-center gap-1 text-xs text-slate-600">
                    Qty
                    <input
                      type="number"
                      min={1}
                      max={99}
                      value={qty}
                      onChange={(e) => onSetQty(id, Math.max(1, Number(e.target.value) || 1))}
                      className="w-16 rounded border border-slate-300 px-2 py-0.5 text-sm"
                    />
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
