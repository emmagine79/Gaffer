/**
 * Which surface the page is on, and which view it showed last there.
 *
 * One web UI serves three surfaces (plan, architecture call 5):
 *   ?surface=menubar  the 360 px panel inside the Swift menu-bar popover
 *   ?surface=window   the full Mac window
 *   no parameter      a phone (or any browser)
 */

export type Surface = 'menubar' | 'window' | 'phone'
export type View = 'glass' | 'desk'

export function readSurface(search: string = location.search): Surface {
  const surface = new URLSearchParams(search).get('surface')
  return surface === 'menubar' || surface === 'window' ? surface : 'phone'
}

const viewKey = (surface: Surface) => `gaffer.view.${surface}`

/** The view this surface showed last. Storage can be missing (private mode): Glass then. */
export function rememberedView(surface: Surface): View {
  try {
    return localStorage.getItem(viewKey(surface)) === 'desk' ? 'desk' : 'glass'
  } catch {
    return 'glass'
  }
}

export function rememberView(surface: Surface, view: View) {
  try {
    localStorage.setItem(viewKey(surface), view)
  } catch { /* private mode: the view still changes, it just is not remembered */ }
}

interface ShellBridge { postMessage: (message: unknown) => void }

/** The Swift shell's message handler. Only the menu-bar panel's WKWebView has it. */
function shellBridge(): ShellBridge | null {
  const webkit = (window as { webkit?: { messageHandlers?: { gaffer?: ShellBridge } } }).webkit
  return webkit?.messageHandlers?.gaffer ?? null
}

/** Ask the Swift shell to open the full Gaffer window. False when there is no shell to ask. */
export function openWindow(): boolean {
  const bridge = shellBridge()
  if (!bridge) return false
  bridge.postMessage({ type: 'open-window' })
  return true
}
