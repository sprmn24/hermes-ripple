import { useCallback, useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'
import { PALETTE_AREA, host } from '@hermes/plugin-sdk'

const BADGES = {
  fresh: { text: 'fresh', color: '#16a34a' },
  stale: { text: 'stale', color: '#d97706' },
  unapproved: { text: 'unapproved', color: '#6b7280' }
}

const GROUPS = [
  { kind: 'source', label: 'Sources' },
  { kind: 'compute', label: 'Computations' },
  { kind: 'artifact', label: 'Artifacts' }
]

function badgeOf(node) {
  if (node.state === 'stale' || node.fresh === false) return BADGES.stale
  if (node.kind === 'artifact' && node.approved_revision == null) {
    return BADGES.unapproved
  }
  return BADGES.fresh
}

function displayValue(node) {
  if (node.kind === 'artifact') return node.summary == null ? '' : String(node.summary)
  const v = node.value
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function causeLine(node) {
  if (node.state !== 'stale') return null
  if (node.cause_path && node.cause_path.length) {
    return (node.cause || '') + '  (' + node.cause_path.join(' -> ') + ')'
  }
  return node.cause || 'stale'
}

function Badge({ badge }) {
  return jsx('span', {
    style: {
      color: badge.color,
      backgroundColor: badge.color + '1f',
      border: '1px solid ' + badge.color + '4d',
      borderRadius: '9999px',
      padding: '0 6px',
      fontSize: '0.6875rem',
      lineHeight: '1.1rem',
      whiteSpace: 'nowrap'
    },
    children: badge.text
  })
}

function NodeRow({ node, onApprove, approving }) {
  const badge = badgeOf(node)
  const isArtifact = node.kind === 'artifact'
  const canApprove = isArtifact && node.fresh === true && node.approved_revision == null
  const cause = causeLine(node)

  return jsx('div', {
    className: 'rounded border border-(--ui-border) p-2',
    children: jsxs('div', {
      className: 'flex flex-col gap-1',
      children: [
        jsxs('div', {
          className: 'flex items-center justify-between gap-2',
          children: [
            jsx('span', {
              className: 'font-mono text-xs text-(--ui-text-primary) truncate',
              children: node.node_id
            }),
            jsxs('div', {
              className: 'flex items-center gap-1 shrink-0',
              children: [
                jsx('span', {
                  className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
                  children: 'r' + node.revision
                }),
                jsx(Badge, { badge })
              ]
            })
          ]
        }),
        jsx('div', {
          className: 'text-xs text-(--ui-text-secondary) break-words',
          children: displayValue(node)
        }),
        cause
          ? jsx('div', {
              className: 'text-[0.6875rem] text-(--ui-text-warning, #d97706) break-words',
              children: cause
            })
          : null,
        isArtifact
          ? jsxs('div', {
              className: 'flex items-center justify-between gap-2 mt-0.5',
              children: [
                jsx('span', {
                  className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
                  children:
                    node.approved_revision == null
                      ? 'needs approval'
                      : 'approved r' + node.approved_revision
                }),
                jsx('button', {
                  type: 'button',
                  className:
                    'rounded px-2 py-0.5 text-[0.6875rem] text-white ' +
                    (canApprove ? 'bg-(--ui-accent)' : 'bg-(--ui-text-tertiary)') +
                    ' disabled:opacity-50',
                  disabled: !canApprove || approving,
                  onClick: () => onApprove(node),
                  children: approving ? '…' : 'Approve'
                })
              ]
            })
          : null
      ]
    })
  })
}

function RipplePane({ ctx }) {
  const [graph, setGraph] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const data = await ctx.rest('/graph')
      setGraph(data)
      setError(null)
    } catch (e) {
      setError('error: ' + (e && e.message ? e.message : String(e)))
    }
  }, [ctx])

  useEffect(() => {
    load()
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [load])

  const run = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      await load()
    } catch (e) {
      setError('error: ' + (e && e.message ? e.message : String(e)))
    } finally {
      setBusy(false)
    }
  }

  const approve = (node) =>
    run(() =>
      ctx.rest('/approve', {
        method: 'POST',
        body: { artifact_id: node.node_id, revision: node.revision }
      })
    )

  const reset = () => run(() => ctx.rest('/demo/reset', { method: 'POST' }))

  const nodes = graph && Array.isArray(graph.nodes) ? graph.nodes : []
  const releases = graph && Array.isArray(graph.releases) ? graph.releases : []

  return jsxs('div', {
    className: 'flex h-full flex-col gap-3 p-3 text-sm overflow-y-auto',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between gap-2',
        children: [
          jsx('div', { className: 'font-medium', children: 'Ripple' }),
          jsxs('div', {
            className: 'flex gap-2',
            children: [
              jsx('button', {
                type: 'button',
                className: 'rounded px-2 py-1 text-xs bg-(--ui-accent) text-white disabled:opacity-50',
                onClick: reset,
                disabled: busy,
                children: 'Reset demo'
              }),
              jsx('button', {
                type: 'button',
                className:
                  'rounded px-2 py-1 text-xs border border-(--ui-border) text-(--ui-text-primary) disabled:opacity-50',
                onClick: load,
                disabled: busy,
                children: 'Refresh'
              })
            ]
          })
        ]
      }),
      error
        ? jsx('div', {
            className: 'text-xs text-(--ui-text-warning, #d97706) break-words',
            children: error
          })
        : null,
      ...GROUPS.map((g) => {
        const members = nodes.filter((n) => n.kind === g.kind)
        return jsxs('div', {
          key: g.kind,
          className: 'flex flex-col gap-1.5',
          children: [
            jsx('div', {
              className: 'text-[0.6875rem] uppercase tracking-wide text-(--ui-text-tertiary)',
              children: g.label + ' (' + members.length + ')'
            }),
            members.length
              ? members.map((n) =>
                  jsx(NodeRow, {
                    key: n.node_id,
                    node: n,
                    onApprove: approve,
                    approving: busy
                  })
                )
              : jsx('div', {
                  className: 'text-xs text-(--ui-text-tertiary)',
                  children: 'none'
                })
          ]
        })
      }),
      jsxs('div', {
        className: 'flex flex-col gap-1.5',
        children: [
          jsx('div', {
            className: 'text-[0.6875rem] uppercase tracking-wide text-(--ui-text-tertiary)',
            children: 'Releases (' + releases.length + ')'
          }),
          releases.length
            ? releases.map((r) =>
                jsx('div', {
                  key: r.artifact_id + ':' + r.revision + ':' + r.published_at,
                  className: 'font-mono text-xs text-(--ui-text-secondary) break-all',
                  children:
                    String(r.artifact_id) +
                    '  r' +
                    r.revision +
                    '  ' +
                    String(r.content_hash || '').slice(0, 8)
                })
              )
            : jsx('div', {
                className: 'text-xs text-(--ui-text-tertiary)',
                children: 'none'
              })
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
        width: '360px',
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
