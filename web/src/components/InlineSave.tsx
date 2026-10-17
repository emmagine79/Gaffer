import { Check, X } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Key } from './Controls'

/** A button that turns into a name field, for saving looks, presets and timelines. */
export function InlineSave({
  label, icon, placeholder, onSave, kind = 'ghost',
}: {
  label: string
  icon?: ReactNode
  placeholder: string
  onSave: (name: string) => void | Promise<void>
  kind?: 'ghost' | 'plain' | 'primary'
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) ref.current?.focus()
  }, [editing])

  const commit = async () => {
    const value = name.trim()
    if (!value) return
    await onSave(value)
    setName('')
    setEditing(false)
  }

  if (!editing) {
    return <Key kind={kind} onClick={() => setEditing(true)}>{icon}{label}</Key>
  }
  return (
    <form className="inline-save" onSubmit={(e) => { e.preventDefault(); void commit() }}>
      <input
        ref={ref}
        className="input"
        value={name}
        placeholder={placeholder}
        aria-label={placeholder}
        maxLength={60}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && setEditing(false)}
      />
      <Key type="submit" kind="primary" disabled={!name.trim()} title="Save"><Check /></Key>
      <Key kind="ghost" onClick={() => setEditing(false)} title="Cancel"><X /></Key>
    </form>
  )
}
