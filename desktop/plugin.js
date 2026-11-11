import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'
import { PALETTE_AREA, host } from '@hermes/plugin-sdk'

function RipplePane({ ctx }) {
  const [graph, setGraph] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = async () => {
    setBusy(true)
    setError(null)
    try {
      const data = await ctx.rest('/graph')
      setGraph(data)
    } catch (e) {
      setError('error: ' + (e && e.message ? e.message : String(e)))
    } finally {
      setBusy(false)
    }
  }

  const nodes = graph && Array.isArray(graph.nodes) ? graph.nodes : []
  const byState = {}
  for (const n of nodes) {
    byState[n.state] = (byState[n.state] || 0) + 1
  }
  const stateSummary = Object.keys(byState)
    .map((s) => `${s}: ${byState[s]}`)
    .join(', ')

  return jsxs('div', {
    className: 'flex h-full flex-col gap-2 p-3 text-sm',
    children: [
      jsx('div', { className: 'font-medium', children: 'Ripple' }),
      jsx('button', {
        type: 'button',
        className: 'rounded px-2 py-1 text-white bg-(--ui-accent) disabled:opacity-50',
        onClick: load,
        disabled: busy,
        children: busy ? 'loading…' : 'Refresh graph'
      }),
      error
        ? jsx('pre', {
            className: 'whitespace-pre-wrap text-(--ui-text-secondary)',
            children: error
          })
        : jsx('div', {
            className: 'flex flex-col gap-1 text-(--ui-text-secondary)',
            children: [
              jsx('div', { children: `nodes: ${nodes.length}` }),
              jsx('div', { children: `states: ${stateSummary || '—'}` }),
              ...nodes.map((n) =>
                jsx('div', {
                  key: n.node_id,
                  children: `${n.node_id} · ${n.kind} · ${n.state} · rev ${n.revision}`
                })
              )
            ]
          })
    ]
  })
}

export default {
  id: 'ripple',
  name: 'Ripple',
  register(ctx) {
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'Ripple',
      data: {
        placement: 'main',
        width: '300px',
        dock: { pane: 'workspace', pos: 'right', enforce: true }
      },
      render: () => jsx(RipplePane, { ctx })
    })

    ctx.register({
      id: 'open-panel',
      area: PALETTE_AREA,
      data: {
        id: 'ripple.open-panel',
        label: 'Ripple: Open panel',
        keywords: ['ripple', 'pane', 'graph'],
        run: () => host.revealPane('ripple:pane')
      }
    })
  }
}
