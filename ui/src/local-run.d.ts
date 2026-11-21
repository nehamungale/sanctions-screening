declare module 'virtual:local-run' {
  type LocalFile = { name: string; text: string }
  /** This repository's own run, read from disk by the dev server. Always null in a build. */
  const run: { trace: LocalFile | null; alerts: LocalFile | null } | null
  export default run
}
