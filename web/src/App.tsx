import { useEffect } from 'react'
import { AddLight } from './app/AddLight'
import { ConnectionScreen } from './app/ConnectionScreen'
import { MasterBar } from './app/MasterBar'
import { CommandPalette, Toasts, useShortcuts } from './app/Overlays'
import { Rail } from './app/Rail'
import { TABS, tabAvailable, tabBlurb } from './app/tabs'
import { startHistory } from './state/history'
import { startLiveTheme } from './state/liveTheme'
import { startSyncSessions } from './state/syncSessions'
import { useStudio } from './state/store'
import { ColourTab } from './tabs/ColourTab'
import { DeviceTab } from './tabs/DeviceTab'
import { EffectsTab } from './tabs/EffectsTab'
import { GelsTab } from './tabs/GelsTab'
import { GuideTab } from './tabs/GuideTab'
import { LabTab } from './tabs/LabTab'
import { LiveTab } from './tabs/LiveTab'
import { MeshTab } from './tabs/MeshTab'
import { ScenesTab } from './tabs/ScenesTab'
import { ScheduleTab } from './tabs/ScheduleTab'
import { SyncTab } from './tabs/SyncTab'
import { TimelineTab } from './tabs/TimelineTab'
import { WhiteTab } from './tabs/WhiteTab'
import './app/shell.css'

const VIEWS = {
  live: LiveTab, white: WhiteTab, colour: ColourTab, gels: GelsTab, effects: EffectsTab, timeline: TimelineTab,
  sync: SyncTab, scenes: ScenesTab, schedule: ScheduleTab, mesh: MeshTab, device: DeviceTab, lab: LabTab,
  guide: GuideTab,
} as const

/** Tabs about every light rather than the selected one: switching lights must not remount them. */
const STUDIO_WIDE = new Set(['mesh', 'guide', 'scenes', 'schedule'])

/** Tabs that work with no light at all, so the studio is never a dead end. */
const WITHOUT_LIGHT = new Set(['mesh', 'guide', 'scenes', 'schedule', 'device'])

export default function App() {
  const tab = useStudio((s) => s.tab)
  const ready = useStudio((s) => s.ready)
  const caps = useStudio((s) => s.caps)
  const hasLight = useStudio((s) => s.light !== null)
  const gelCount = useStudio((s) => s.gels.length)
  const setTab = useStudio((s) => s.setTab)
  const selected = useStudio((s) => s.selected)
  useShortcuts()
  useEffect(() => startLiveTheme(), [])
  useEffect(() => startHistory(), [])
  useEffect(() => startSyncSessions(), [])

  const def = TABS.find((t) => t.id === tab)
  const usable = def ? tabAvailable(def, caps) : false
  useEffect(() => {
    // Switching to a light that cannot use this tab (colour on a bi-colour light): go somewhere it can.
    if (ready && !usable) setTab(hasLight ? 'live' : 'mesh')
  }, [ready, usable, hasLight, setTab])

  const View = VIEWS[tab] ?? LiveTab
  const showView = ready && usable && (hasLight || WITHOUT_LIGHT.has(tab))

  return (
    <div className="studio">
      <div className="seamless" aria-hidden="true" />
      <Rail />
      <main className="stage" id="main">
        {/* Keyed by tab and light, so each mounts fresh with a short CSS fade when either changes. */}
        <div key={STUDIO_WIDE.has(tab) ? tab : `${tab}:${selected ?? ''}`} className="stage-inner">
          <header className="stage-head">
            <h1>{def?.name}</h1>
            <p className="muted">{def ? tabBlurb(def, caps, gelCount) : ''}</p>
          </header>
          {showView ? <View /> : <div className="stage-loading muted">{ready ? '' : 'Opening the studio'}</div>}
        </div>
      </main>
      <MasterBar />
      <Toasts />
      <CommandPalette />
      <ConnectionScreen />
      <AddLight />
    </div>
  )
}
