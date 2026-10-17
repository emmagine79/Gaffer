// The studio and its stylesheets, loaded together once the PIN gate lets the page in (SPEC-015).
// The stylesheets stay after the studio's own imports, as they were when main.tsx imported them
// after App: several rules (the focus ring, for one) depend on that order.
import { Shell } from './Shell'
import '../styles/tokens.css'
import '../styles/base.css'
import '../styles/glass.css'

export default Shell
