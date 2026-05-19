export default function IslandsBar({
  groups,
  islandsByName,
  settings,
  onIslandChange,
  onToggleOwned,
  onIncludeNonRareChange,
}) {
  return (
    <section className="rounded-md border border-slate-200 bg-white px-4 py-3">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Islands
      </h2>

      <div className="space-y-3">
        {groups.map((group) => (
          <IslandGroup
            key={group.label}
            label={group.label}
            names={group.islands}
            islandsByName={islandsByName}
            settings={settings}
            onIslandChange={onIslandChange}
            onToggleOwned={onToggleOwned}
          />
        ))}
      </div>

      <label className="mt-3 flex items-center gap-2 border-t border-slate-100 pt-3 text-sm">
        <input
          type="checkbox"
          className="size-4 rounded border-slate-400 text-indigo-600 focus:ring-indigo-500"
          checked={!!settings.include_non_rare}
          onChange={(e) => onIncludeNonRareChange(e.target.checked)}
        />
        <span>Include non-rare breeding recipes</span>
      </label>
    </section>
  )
}

function IslandGroup({ label, names, islandsByName, settings, onIslandChange, onToggleOwned }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
        {names.map((internal) => (
          <IslandRow
            key={internal}
            internal={internal}
            island={islandsByName[internal]}
            config={settings.islands[internal]}
            onIslandChange={onIslandChange}
            onToggleOwned={onToggleOwned}
          />
        ))}
      </div>
    </div>
  )
}

function IslandRow({ internal, island, config, onIslandChange, onToggleOwned }) {
  if (!island) return null
  const owned = !!config
  const bonus = (config?.structures ?? 1) > 1
  const enhanced = !!config?.enhanced

  return (
    <div className="flex items-center gap-2 py-0.5 text-sm">
      <label className="flex flex-1 cursor-pointer items-center gap-2">
        <input
          type="checkbox"
          className="size-4 shrink-0 rounded border-slate-400 text-indigo-600 focus:ring-indigo-500"
          checked={owned}
          onChange={(e) => onToggleOwned(internal, e.target.checked)}
        />
        <span className={owned ? 'text-slate-900' : 'text-slate-500'}>
          {island.display_name}
        </span>
      </label>
      {owned && (
        <div className="flex items-center gap-3 text-xs text-slate-600">
          <label className="flex cursor-pointer items-center gap-1">
            <input
              type="checkbox"
              className="size-3.5 rounded border-slate-400 text-indigo-600 focus:ring-indigo-500"
              checked={bonus}
              onChange={(e) =>
                onIslandChange(internal, { structures: e.target.checked ? 2 : 1 })
              }
            />
            Bonus
          </label>
          <label className="flex cursor-pointer items-center gap-1">
            <input
              type="checkbox"
              className="size-3.5 rounded border-slate-400 text-indigo-600 focus:ring-indigo-500"
              checked={enhanced}
              onChange={(e) => onIslandChange(internal, { enhanced: e.target.checked })}
            />
            Enhanced
          </label>
        </div>
      )}
    </div>
  )
}
