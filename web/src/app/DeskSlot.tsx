/**
 * The lighting desk's place in the panel. SPEC-007 replaces this with the desk from
 * design/directions/b-desk.html (one fader and readout per light, numbered looks).
 */
export function DeskSlot() {
  return (
    <div className="desk-slot" data-slot="desk">
      <p className="g-name">All lights</p>
      <p className="g-dim">The lighting desk is coming in the next update. Switch back to One light to control each light.</p>
    </div>
  )
}
