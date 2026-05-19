import { useEffect, useMemo, useRef, useState } from 'react'
import {
  fetchBoxMonsters,
  fetchIslands,
  fetchSettings,
  generatePlan,
  saveSettings,
  triggerDownload,
} from './api'
import IslandsBar from './components/IslandsBar.jsx'
import GeneratePanel from './components/GeneratePanel.jsx'

export default function App() {
  const [islands, setIslands] = useState([])
  const [groups, setGroups] = useState([])
  const [boxMonsters, setBoxMonsters] = useState([])
  const [settings, setSettings] = useState({
    islands: {},
    targets: {},
    include_non_rare: true,
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('Loading…')
  const [busy, setBusy] = useState(false)
  const [generateError, setGenerateError] = useState(null)
  const initialLoadDone = useRef(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [islandsResp, boxResp, settingsResp] = await Promise.all([
          fetchIslands(),
          fetchBoxMonsters(),
          fetchSettings(),
        ])
        if (cancelled) return
        setIslands(islandsResp.islands)
        setGroups(islandsResp.groups || [])
        setBoxMonsters(boxResp.monsters)
        setSettings({
          islands: settingsResp.islands || {},
          targets: settingsResp.targets || {},
          include_non_rare: !!settingsResp.include_non_rare,
        })
        // Flag that the initial load finished — *after* this point, settings
        // changes should auto-save.  See the auto-save effect below.
        setTimeout(() => {
          initialLoadDone.current = true
        }, 0)
        setStatus('Ready.')
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const islandsByName = useMemo(() => {
    const m = {}
    for (const isl of islands) m[isl.internal_name] = isl
    return m
  }, [islands])

  const boxById = useMemo(() => {
    const m = {}
    for (const b of boxMonsters) m[b.id] = b
    return m
  }, [boxMonsters])

  function updateIsland(internal, patch) {
    setSettings((s) => {
      const next = { ...s.islands }
      const existing = next[internal] || { structures: 2, enhanced: false }
      const merged = { ...existing, ...patch }
      next[internal] = merged
      if (patch.owned === false) delete next[internal]
      return { ...s, islands: next }
    })
  }

  function toggleIslandOwned(internal, owned) {
    if (owned) {
      const existing = settings.islands[internal] || { structures: 1, enhanced: false }
      updateIsland(internal, { structures: existing.structures, enhanced: existing.enhanced })
    } else {
      setSettings((s) => {
        const next = { ...s.islands }
        delete next[internal]
        return { ...s, islands: next }
      })
    }
  }

  // Auto-save: persist on every settings change after the initial load.
  useEffect(() => {
    if (!initialLoadDone.current) return
    let cancelled = false
    saveSettings(settings)
      .then(() => {
        if (!cancelled) setStatus('Saved.')
      })
      .catch((e) => {
        if (!cancelled) setStatus(`Save failed: ${e.message}`)
      })
    return () => {
      cancelled = true
    }
  }, [settings])

  function setIncludeNonRare(v) {
    setSettings((s) => ({ ...s, include_non_rare: v }))
  }

  function setTargetQty(mid, qty) {
    setSettings((s) => {
      const next = { ...s.targets }
      const id = String(mid)
      if (qty > 0) next[id] = qty
      else delete next[id]
      return { ...s, targets: next }
    })
  }

  async function onGenerate() {
    setBusy(true)
    setStatus('Generating plan…')
    setGenerateError(null)
    try {
      const { blob, summary } = await generatePlan(settings)
      triggerDownload(blob)
      const skipped = summary.skipped ? ` · ${summary.skipped} non-rare skipped` : ''
      setStatus(
        `Generated ${summary.rows} breed rows across ${summary.islands} island(s)${skipped}.`
      )
    } catch (e) {
      if (e.code === 'missing_islands' && e.details?.missing_by_target) {
        setGenerateError({ message: e.message, details: e.details })
        setStatus('Cannot generate — missing islands.')
      } else {
        setGenerateError({ message: e.message, details: null })
        setStatus(`Generation failed: ${e.message}`)
      }
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-slate-500">
        Loading planner…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-red-600">
        Failed to reach API: {error}
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col p-6">
      <header className="mb-4 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">MSM Breeding Planner</h1>
        <span className="text-xs text-slate-500">
          {boxMonsters.length} box monsters · {islands.length} islands
        </span>
      </header>

      <IslandsBar
        groups={groups}
        islandsByName={islandsByName}
        settings={settings}
        onIslandChange={updateIsland}
        onToggleOwned={toggleIslandOwned}
        onIncludeNonRareChange={setIncludeNonRare}
      />

      <main className="mt-4 flex-1 overflow-hidden">
        <GeneratePanel
          boxMonsters={boxMonsters}
          boxById={boxById}
          targets={settings.targets}
          onSetQty={setTargetQty}
        />
      </main>

      {generateError && (
        <div className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-sm shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <p className="font-medium text-red-700">{generateError.message}</p>
            <button
              onClick={() => setGenerateError(null)}
              className="text-red-400 hover:text-red-700"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
          {generateError.details?.missing_by_target?.length > 0 && (
            <ul className="mt-2 space-y-2 text-red-800">
              {generateError.details.missing_by_target.map((t) => (
                <li key={t.target_id}>
                  <p className="font-medium">{t.target_name} is missing:</p>
                  <ul className="ml-4 list-disc">
                    {t.missing.map((m) => (
                      <li key={m.monster_id}>
                        <span className="font-medium">{m.display_name}</span>
                        {m.available_on?.length > 0 ? (
                          <> — add an island: {m.available_on.join(', ')}</>
                        ) : (
                          <> — no selectable island provides this monster</>
                        )}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <footer className="mt-4 flex items-center justify-between gap-3 border-t border-slate-200 pt-3">
        <span className="text-sm text-slate-500">{status}</span>
        <button
          onClick={onGenerate}
          disabled={busy}
          className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
        >
          {busy ? 'Working…' : 'Generate Plan'}
        </button>
      </footer>
    </div>
  )
}

