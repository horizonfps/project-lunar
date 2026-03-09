import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { Map, X, RefreshCw, Search } from 'lucide-react'
import { fetchWorldGraph, searchWorldGraph } from '../api'

const NODE_COLORS = {
  NPC: '#a78bfa',
  LOCATION: '#34d399',
  FACTION: '#fbbf24',
  ITEM: '#22d3ee',
  EVENT: '#fb7185',
}

const NODE_RADIUS = {
  NPC: 6,
  LOCATION: 8,
  FACTION: 7,
  ITEM: 5,
  EVENT: 5,
}

const TYPE_POSITIONS = {
  LOCATION: { x: 0, y: 0 },
  NPC: { x: 80, y: -60 },
  FACTION: { x: -80, y: -60 },
  ITEM: { x: 60, y: 80 },
  EVENT: { x: -60, y: 80 },
}

export default function WorldMapModal({ open, onClose, campaignId }) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [loading, setLoading] = useState(false)
  const [hoverNode, setHoverNode] = useState(null)
  const [hoverLink, setHoverLink] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 })
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searchHighlightSet, setSearchHighlightSet] = useState(null)
  const graphRef = useRef()
  const containerRef = useRef()

  const loadGraph = async () => {
    if (!campaignId) return
    setLoading(true)
    try {
      const data = await fetchWorldGraph(campaignId)
      setGraphData(data)
    } catch {
      setGraphData({ nodes: [], links: [] })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      loadGraph()
      setSelectedNode(null)
      setSearchHighlightSet(null)
    }
  }, [open, campaignId])

  // Clustering forces — apply after graph mounts / data changes
  useEffect(() => {
    if (!graphRef.current || graphData.nodes.length === 0) return

    const STRENGTH = 0.05
    // Custom force function that nudges nodes toward type-based positions
    const clusterForce = (alpha) => {
      graphData.nodes.forEach((node) => {
        const pos = TYPE_POSITIONS[node.node_type]
        if (!pos) return
        node.vx += (pos.x - (node.x || 0)) * STRENGTH * alpha
        node.vy += (pos.y - (node.y || 0)) * STRENGTH * alpha
      })
    }
    clusterForce.initialize = () => {}
    graphRef.current.d3Force('cluster', clusterForce)
    graphRef.current.d3ReheatSimulation()
  }, [graphData])

  // Compute link counts per node
  const linkCountMap = useMemo(() => {
    const counts = {}
    graphData.links.forEach((link) => {
      const srcId = typeof link.source === 'object' ? link.source.id : link.source
      const tgtId = typeof link.target === 'object' ? link.target.id : link.target
      counts[srcId] = (counts[srcId] || 0) + 1
      counts[tgtId] = (counts[tgtId] || 0) + 1
    })
    return counts
  }, [graphData.links])

  const highlightSet = useMemo(() => {
    if (!hoverNode) return null
    const neighbors = new Set([hoverNode.id])
    graphData.links.forEach((link) => {
      const srcId = typeof link.source === 'object' ? link.source.id : link.source
      const tgtId = typeof link.target === 'object' ? link.target.id : link.target
      if (srcId === hoverNode.id) neighbors.add(tgtId)
      if (tgtId === hoverNode.id) neighbors.add(srcId)
    })
    return neighbors
  }, [hoverNode, graphData.links])

  // Build search highlight set from search results
  useEffect(() => {
    if (searchResults.length === 0) {
      setSearchHighlightSet(null)
      return
    }
    const matchedIds = new Set()
    const nodeNames = graphData.nodes.map((n) => ({
      id: n.id,
      nameLower: (n.name || '').toLowerCase(),
    }))
    searchResults.forEach((r) => {
      const factLower = (r.fact || '').toLowerCase()
      nodeNames.forEach(({ id, nameLower }) => {
        if (nameLower && factLower.includes(nameLower)) {
          matchedIds.add(id)
        }
      })
    })
    setSearchHighlightSet(matchedIds.size > 0 ? matchedIds : null)
  }, [searchResults, graphData.nodes])

  const nodeCanvasObject = useCallback(
    (node, ctx, globalScale) => {
      const isHighlighted = !highlightSet || highlightSet.has(node.id)
      const isSearchMatch = searchHighlightSet && searchHighlightSet.has(node.id)
      const radius = NODE_RADIUS[node.node_type] || 5
      const color = NODE_COLORS[node.node_type] || '#94a3b8'
      const nodeLinks = linkCountMap[node.id] || 0
      const isImportant = nodeLinks >= 3 || node.node_type === 'LOCATION'

      // Search highlight — pulsing glow ring
      if (isSearchMatch) {
        const pulse = Math.sin(Date.now() / 300) * 0.3 + 0.7 // 0.4 to 1.0
        const glowRadius = radius + 5
        ctx.beginPath()
        ctx.arc(node.x, node.y, glowRadius, 0, 2 * Math.PI)
        ctx.strokeStyle = color
        ctx.lineWidth = 2.5
        ctx.globalAlpha = pulse
        ctx.stroke()
        ctx.globalAlpha = 1
      }

      // Node circle
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
      ctx.fillStyle = isHighlighted ? color : color + '33'
      ctx.fill()

      if (isHighlighted && globalScale > 0.8) {
        ctx.strokeStyle = color + '66'
        ctx.lineWidth = 1.5
        ctx.stroke()
      }

      // Label — always show for important nodes, otherwise only when zoomed or hovered
      const showLabel =
        isImportant || globalScale > 1.2 || (hoverNode && hoverNode.id === node.id)

      if (showLabel) {
        const label = node.name
        const baseFontSize = isImportant ? 12 : 10
        const fontSize = Math.max(baseFontSize / globalScale, 3)
        ctx.font = `${isImportant ? 'bold ' : ''}${fontSize}px sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillStyle = isHighlighted ? '#e2e8f0' : '#64748b'
        ctx.fillText(label, node.x, node.y + radius + 2)
      }
    },
    [hoverNode, highlightSet, linkCountMap, searchHighlightSet],
  )

  // Link canvas object — draw edge label on hover
  const linkCanvasObject = useCallback(
    (link, ctx, globalScale) => {
      if (link !== hoverLink) return
      const relType = link.rel_type
      if (!relType) return

      const src = link.source
      const tgt = link.target
      if (!src || !tgt || src.x == null || tgt.x == null) return

      const midX = (src.x + tgt.x) / 2
      const midY = (src.y + tgt.y) / 2

      const fontSize = Math.max(10 / globalScale, 3)
      ctx.font = `${fontSize}px sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'

      // Background for readability
      const text = relType.replace(/_/g, ' ')
      const textWidth = ctx.measureText(text).width
      const padding = 2 / globalScale
      ctx.fillStyle = 'rgba(15, 23, 42, 0.85)'
      ctx.fillRect(
        midX - textWidth / 2 - padding,
        midY - fontSize / 2 - padding,
        textWidth + padding * 2,
        fontSize + padding * 2,
      )

      ctx.fillStyle = '#cbd5e1'
      ctx.fillText(text, midX, midY)
    },
    [hoverLink],
  )

  const linkColor = useCallback(
    (link) => {
      if (link === hoverLink) return 'rgba(148, 163, 184, 0.8)'
      if (!hoverNode) return 'rgba(148, 163, 184, 0.2)'
      const srcId = typeof link.source === 'object' ? link.source.id : link.source
      const tgtId = typeof link.target === 'object' ? link.target.id : link.target
      if (srcId === hoverNode.id || tgtId === hoverNode.id) {
        return 'rgba(148, 163, 184, 0.6)'
      }
      return 'rgba(148, 163, 184, 0.05)'
    },
    [hoverNode, hoverLink],
  )

  const handleNodeClick = useCallback((node, event) => {
    setSelectedNode(node)
    const rect = containerRef.current?.getBoundingClientRect()
    if (rect) {
      setTooltipPos({
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      })
    }
  }, [])

  const handleSearch = async () => {
    if (!searchQuery.trim() || !campaignId) return
    const data = await searchWorldGraph(campaignId, searchQuery)
    setSearchResults(data.facts || [])
  }

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null)
  }, [])

  // Zoom to fit when simulation stabilizes
  const handleEngineStop = useCallback(() => {
    graphRef.current?.zoomToFit(400, 50)
  }, [])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div
        ref={containerRef}
        className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] w-full max-w-4xl mx-4 overflow-hidden flex flex-col"
        style={{ height: '80vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 flex-none">
          <div className="flex items-center gap-3">
            <Map size={16} className="text-emerald-400" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">World Map</h2>
            {graphData.nodes.length > 0 && (
              <span className="text-white/20 text-xs ml-2">
                {graphData.nodes.length} nodes &middot; {graphData.links.length} links
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadGraph}
              disabled={loading}
              className="text-white/40 hover:text-white transition-colors p-1"
              title="Refresh"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 px-6 py-2 border-b border-white/5 flex-none">
          {Object.entries(NODE_COLORS).map(([type, color]) => (
            <div key={type} className="flex items-center gap-1.5">
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-[10px] text-white/40 uppercase tracking-wider">{type}</span>
            </div>
          ))}
        </div>

        {/* Search */}
        <div className="px-6 py-2 border-b border-white/5 flex-none">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Search world facts..."
              className="flex-1 bg-white/[0.03] text-gray-200 text-sm rounded-lg px-3 py-1.5 border border-white/10 focus:outline-none focus:border-white/40 focus:bg-white/[0.05] placeholder-white/20"
            />
            <button
              onClick={handleSearch}
              className="text-white/40 hover:text-white transition-colors p-1.5"
              title="Search"
            >
              <Search size={14} />
            </button>
          </div>
          {searchResults.length > 0 && (
            <div className="mt-2 mb-1 p-2 bg-gray-800/50 rounded text-sm max-h-32 overflow-y-auto relative">
              <button
                onClick={() => setSearchResults([])}
                className="absolute top-1 right-1 text-white/20 hover:text-white transition-colors"
                title="Clear results"
              >
                <X size={12} />
              </button>
              {searchResults.map((r, i) => (
                <div key={i} className="text-gray-300 py-1 border-b border-gray-700/50 last:border-0">
                  {r.fact}
                  {r.valid_at && <span className="text-gray-500 text-xs ml-2">from {r.valid_at}</span>}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Graph */}
        <div className="flex-1 relative" onClick={handleBackgroundClick}>
          {graphData.nodes.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <Map size={32} className="text-white/20 mx-auto mb-3" />
                <p className="text-white/20 text-sm font-light">
                  {loading
                    ? 'Mapping world topology...'
                    : 'No world data yet. Play to populate the graph.'}
                </p>
              </div>
            </div>
          ) : (
            <ForceGraph2D
              ref={graphRef}
              graphData={graphData}
              nodeCanvasObject={nodeCanvasObject}
              linkColor={linkColor}
              linkWidth={(link) => Math.max((link.strength || 0.5) * 2, 0.5)}
              linkCanvasObjectMode={() => 'after'}
              linkCanvasObject={linkCanvasObject}
              linkDirectionalParticles={0}
              onNodeHover={setHoverNode}
              onLinkHover={setHoverLink}
              onNodeClick={handleNodeClick}
              onBackgroundClick={handleBackgroundClick}
              onEngineStop={handleEngineStop}
              backgroundColor="transparent"
              width={containerRef.current?.clientWidth || 800}
              height={(containerRef.current?.clientHeight || 600) - 100}
              cooldownTicks={100}
              d3AlphaDecay={0.02}
              d3VelocityDecay={0.3}
            />
          )}

          {/* Tooltip */}
          {selectedNode && (
            <div
              className="absolute z-10 bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] p-4 min-w-[200px] max-w-[280px] shadow-[0_0_40px_rgba(255,255,255,0.15)] pointer-events-none"
              style={{
                left: Math.min(tooltipPos.x + 10, (containerRef.current?.clientWidth || 800) - 300),
                top: Math.min(tooltipPos.y - 10, (containerRef.current?.clientHeight || 600) - 200),
              }}
            >
              <div className="flex items-center gap-2 mb-2">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: NODE_COLORS[selectedNode.node_type] || '#94a3b8' }}
                />
                <span className="text-white font-bold text-sm">{selectedNode.name}</span>
              </div>
              <span
                className="inline-block text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 rounded-full mb-2"
                style={{
                  backgroundColor: (NODE_COLORS[selectedNode.node_type] || '#94a3b8') + '22',
                  color: NODE_COLORS[selectedNode.node_type] || '#94a3b8',
                }}
              >
                {selectedNode.node_type}
              </span>
              {selectedNode.attributes && Object.keys(selectedNode.attributes).length > 0 && (
                <div className="space-y-1 mt-2 border-t border-white/5 pt-2">
                  {Object.entries(selectedNode.attributes)
                    .slice(0, 4)
                    .map(([key, val]) => (
                      <div key={key} className="flex justify-between text-xs">
                        <span className="text-white/40">{key.replace(/_/g, ' ')}</span>
                        <span className="text-[#d1d1d1] font-medium ml-3 truncate max-w-[120px]">
                          {String(val)}
                        </span>
                      </div>
                    ))}
                </div>
              )}
              {selectedNode.node_type === 'NPC' && selectedNode.attributes?.power_level != null && (
                <div className="mt-2 border-t border-white/5 pt-2">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-white/40">Power Level</span>
                    <span className="text-white font-bold">{selectedNode.attributes.power_level}/10</span>
                  </div>
                  <div className="w-full h-1.5 bg-white/[0.03] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-white/10 rounded-full"
                      style={{ width: `${(selectedNode.attributes.power_level / 10) * 100}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
