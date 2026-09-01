const normalizeBasePath = (basePath: string) => {
  const normalized = basePath.trim().replace(/^\/+|\/+$/g, '')

  return normalized ? `/${normalized}` : ''
}

export const withBasePath = (path: string, configuredBasePath = process.env.NEXT_PUBLIC_BASE_PATH || '') => {
  const basePath = normalizeBasePath(configuredBasePath)
  const normalizedPath = `/${path.replace(/^\/+/, '')}`

  if (!basePath || normalizedPath === basePath || normalizedPath.startsWith(`${basePath}/`)) {
    return normalizedPath
  }

  return `${basePath}${normalizedPath}`
}
