import { lazy, Suspense } from 'react'
import { PhoneGate } from './pin/PhoneGate'

// The studio opens its light socket as soon as it loads, so it loads only after the PIN gate has let the page in.
const Shell = lazy(() => import('./app/Shell').then((m) => ({ default: m.Shell })))

export default function App() {
  return (
    <PhoneGate>
      <Suspense fallback={null}>
        <Shell />
      </Suspense>
    </PhoneGate>
  )
}
