import {
  classifyPptSourceGroups,
  commitPptWebSource,
  createDeckBriefJob,
  createPptDataPackage,
  deleteDocumentSource,
  deleteImageSource,
  deletePptDataSource,
  generateDeckBrief,
  generateDeckBriefWithDebug,
  generateNarrativePlan,
  generateNarrativePlanWithDebug,
  generatePptSpec,
  generatePptSpecWithDebug,
  generatePptVisualArtifacts,
  getDeckBriefJob,
  getPptWebSourceLocationDefault,
  listPptDataSources,
  listPptSourceManifest,
  previewPptWebSource,
  regenerateDeckBriefSlide,
  regeneratePptSpecSection,
  retryImageSourceIngest,
  scheduleDocumentParse,
} from '../ppt-planning/api.js'

export function createAgentPptApiAdapterMethods() {
  return {
    requestAgentPptPlanningOutline(payload = {}) {
      return generatePptSpec(payload)
    },
    requestAgentPptPlanningOutlineWithDebug(payload = {}, options = {}) {
      return generatePptSpecWithDebug(payload, options)
    },
    requestAgentPptPlanningOutlineSection(payload = {}) {
      return regeneratePptSpecSection(payload)
    },
    requestAgentPptPlanningDirective(payload = {}) {
      return generateDeckBrief(payload)
    },
    requestAgentPptPlanningDirectiveWithDebug(payload = {}, options = {}) {
      return generateDeckBriefWithDebug(payload, options)
    },
    requestAgentPptPlanningDeckBriefJob(payload = {}) {
      return createDeckBriefJob(payload)
    },
    requestAgentPptPlanningDeckBriefJobStatus(jobId = '') {
      return getDeckBriefJob(jobId)
    },
    requestAgentPptPlanningNarrativePlan(payload = {}) {
      return generateNarrativePlan(payload)
    },
    requestAgentPptPlanningNarrativePlanWithDebug(payload = {}, options = {}) {
      return generateNarrativePlanWithDebug(payload, options)
    },
    requestAgentPptPlanningDirectiveSlide(payload = {}, options = {}) {
      return regenerateDeckBriefSlide(payload, options)
    },
    requestAgentPptPlanningVisualArtifacts(payload = {}) {
      return generatePptVisualArtifacts(payload)
    },
    requestAgentPptPlanningDataSources(areaId = '', options = {}) {
      return listPptDataSources(areaId, options)
    },
    requestAgentPptPlanningSourceManifest(areaId = '', options = {}) {
      return listPptSourceManifest(areaId, options)
    },
    requestAgentPptPlanningDataPackage(payload = {}) {
      return createPptDataPackage(payload)
    },
    requestAgentPptWebSourceLocationDefault(payload = {}) {
      return getPptWebSourceLocationDefault(payload)
    },
    requestAgentPptWebSourcePreview(payload = {}) {
      return previewPptWebSource(payload)
    },
    requestAgentPptWebSourceCommit(payload = {}) {
      return commitPptWebSource(payload)
    },
    requestAgentPptPlanningDocumentDelete(documentId = '') {
      return deleteDocumentSource(documentId)
    },
    requestAgentPptPlanningDocumentParse(documentId = '') {
      return scheduleDocumentParse(documentId)
    },
    requestAgentPptPlanningImageDelete(attachmentId = '', conversationId = '') {
      return deleteImageSource(attachmentId, conversationId)
    },
    requestAgentPptPlanningImageRetry(attachmentId = '', conversationId = '') {
      return retryImageSourceIngest(attachmentId, conversationId)
    },
    requestAgentPptPlanningPersistedSourceDelete(areaId = '', sourceId = '') {
      return deletePptDataSource(areaId, sourceId)
    },
    requestAgentPptSourceGroupClassification(payload = {}) {
      return classifyPptSourceGroups(payload)
    },
  }
}
