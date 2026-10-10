import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { proxyResearchRequest } from '../../../utils/researchBackend'

export default defineHandler(event => proxyResearchRequest(event, getRouterParam(event, 'path') ?? ''))
