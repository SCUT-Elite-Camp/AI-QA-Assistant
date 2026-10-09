import { defineHandler } from 'nitro'
import { proxyResearchRequest } from '../../../utils/researchBackend'

export default defineHandler(event => proxyResearchRequest(event, 'documents'))
