import type { ButtonHTMLAttributes } from 'react'

const variants = {
  primary: 'bg-indigo-600 text-white hover:bg-indigo-500',
  success: 'bg-emerald-600 text-white hover:bg-emerald-500',
  violet: 'bg-violet-600 text-white hover:bg-violet-500',
  outline: 'border border-slate-700 text-slate-200 hover:bg-slate-800',
  ghost: 'text-slate-300 hover:bg-slate-800',
} as const

export function Button({
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof variants }) {
  return (
    <button
      className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
      {...props}
    />
  )
}
