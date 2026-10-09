export type PersonalLibraryRoute = 'attachments' | 'library'

export function isPersonalLibraryRouteEnabled(
  route: PersonalLibraryRoute,
  env: NodeJS.ProcessEnv = process.env
): boolean {
  if (route === 'attachments') return env.ATTACHMENTS_ENABLED === 'true'
  return env.ATTACHMENTS_ENABLED === 'true' && env.PERSONAL_LIBRARY_ENABLED === 'true'
}
