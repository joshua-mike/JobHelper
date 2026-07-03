export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label?: string
  disabled?: boolean
}) {
  return (
    <label
      className={`flex items-center gap-2 text-sm text-slate-300 ${
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'
      }`}
    >
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`h-5 w-9 shrink-0 rounded-full p-0.5 transition-colors ${
          checked ? 'bg-indigo-600' : 'bg-slate-700'
        }`}
      >
        <span
          className={`block h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-4' : ''
          }`}
        />
      </button>
      {label}
    </label>
  )
}
