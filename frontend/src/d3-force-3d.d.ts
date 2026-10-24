declare module 'd3-force-3d' {
  // Only what the graph uses; force-graph ships d3-force-3d without typings.
  export function forceCollide<N>(radius?: number | ((node: N) => number)): {
    (alpha: number): void
    strength(s: number): ReturnType<typeof forceCollide<N>>
    iterations(n: number): ReturnType<typeof forceCollide<N>>
  }
}
