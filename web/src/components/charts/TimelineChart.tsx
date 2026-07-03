import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { TimelinePoint } from '../../api/types'

function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

// "New jobs" is often hundreds/day while proposed/applied are single digits,
// so the small series get their own right-hand axis.
export function TimelineChart({ data }: { data: TimelinePoint[] }) {
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 0, left: -8, bottom: 0 }}>
          <defs>
            <linearGradient id="gNew" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity={0.45} />
              <stop offset="100%" stopColor="#6366f1" stopOpacity={0.03} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={shortDate}
            tick={{ fill: '#64748b', fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: '#1e293b' }}
            minTickGap={28}
          />
          <YAxis
            yAxisId="left"
            tick={{ fill: '#64748b', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            width={42}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fill: '#64748b', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            width={32}
          />
          <Tooltip
            labelFormatter={shortDate}
            contentStyle={{
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: '#94a3b8' }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area
            yAxisId="left"
            type="monotone"
            dataKey="new"
            name="New jobs"
            stroke="#6366f1"
            strokeWidth={2}
            fill="url(#gNew)"
          />
          <Area
            yAxisId="right"
            type="monotone"
            dataKey="proposed"
            name="Proposed"
            stroke="#a78bfa"
            strokeWidth={2}
            fill="transparent"
          />
          <Area
            yAxisId="right"
            type="monotone"
            dataKey="applied"
            name="Applied"
            stroke="#34d399"
            strokeWidth={2}
            fill="transparent"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
