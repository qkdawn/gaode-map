import { asText, cloneArray, cloneObject } from './normalizers.js'
import {
  buildPptAllSourcesFullExportFilename,
  buildPptAllSourcesFullExportPayload,
  buildPptSourceFullExportFilename,
  buildPptSourceFullExportPayload,
  createPptPlanningState,
  getPptSourceSummary,
  markPptDirectiveStaleForSources,
  movePptSourceToGroup,
  removePptSource,
  removePptSourceGroup,
  renamePptSource,
  renamePptSourceGroup,
  setAllPptSourcesSelected,
  setPptGenerationError,
  setPptSourceGroupEmoji,
  setPptSourceGroupSelected,
  setPptSpecField,
  togglePptSourceGroupCollapsed,
  togglePptSourceSelection,
} from '../ppt-planning/ui-state.js'
import {
  documentIdFromPptSource,
  imageAttachmentIdFromPptSource,
  imageConversationIdFromPptSource,
  isPptDocumentSource,
  isPptImageSource,
  isPptPersistedArtifactSource,
} from '../ppt-planning/source-payloads.js'

function uniqueText(items = []) {
  return [...new Set(cloneArray(items).map((item) => asText(item)).filter(Boolean))]
}

function selectedSourceIdsFromState(state = {}) {
  return cloneArray(createPptPlanningState(state).sources)
    .filter((source) => source && source.selected && asText(source.status) === 'ready')
    .map((source) => asText(source.id))
    .filter(Boolean)
}

function changedReadySourceIds(previous = {}, next = {}) {
  const previousIds = new Set(selectedSourceIdsFromState(previous))
  const nextIds = new Set(selectedSourceIdsFromState(next))
  return [...new Set([...previousIds, ...nextIds])].filter((sourceId) => previousIds.has(sourceId) !== nextIds.has(sourceId))
}

function downloadJsonFile(payload = {}, filename = 'export.json') {
  const text = JSON.stringify(payload, null, 2)
  const blob = new Blob([text], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  } finally {
    URL.revokeObjectURL(url)
  }
}

export function createAgentPptSourceActionMethods() {
  return {
    updateAgentActivePptPlanningStateWithSourceStale(nextState = {}, previousState = null, explicitSourceIds = []) {
      const previous = previousState ? createPptPlanningState(previousState) : this.getAgentActivePptPlanningState()
      const changedSourceIds = uniqueText([...cloneArray(explicitSourceIds), ...changedReadySourceIds(previous, nextState)])
      const staleState = markPptDirectiveStaleForSources(nextState, changedSourceIds)
      this.updateAgentActivePptPlanningState(staleState)
    },
    toggleAgentPptPlanningSource(sourceId = '') {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      this.updateAgentActivePptPlanningStateWithSourceStale(togglePptSourceSelection(state, sourceId), state, [sourceId])
    },
    toggleAgentPptPlanningSourceGroupCollapsed(groupId = '') {
      this.updateAgentActivePptPlanningState(togglePptSourceGroupCollapsed(this.getAgentPptPlanningStateWithSystemSources(), groupId))
    },
    setAgentPptPlanningSourceGroupSelected(groupId = '', selected = true) {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      this.updateAgentActivePptPlanningStateWithSourceStale(setPptSourceGroupSelected(state, groupId, selected), state)
    },
    moveAgentPptPlanningSourceToGroup(sourceId = '', groupId = '') {
      this.updateAgentActivePptPlanningState(movePptSourceToGroup(this.getAgentPptPlanningStateWithSystemSources(), sourceId, groupId))
    },
    renameAgentPptPlanningSource(sourceId = '', title = '') {
      this.updateAgentActivePptPlanningState(renamePptSource(this.getAgentPptPlanningStateWithSystemSources(), sourceId, title))
    },
    exportAgentPptPlanningSource(sourceId = '') {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const id = asText(sourceId)
      const source = cloneArray(state.sources).find((item) => asText(item && item.id) === id)
      const payload = buildPptSourceFullExportPayload(state, id)
      if (!source || !payload) return null
      const filename = buildPptSourceFullExportFilename(source)
      downloadJsonFile(payload, filename)
      return { filename, payload }
    },
    exportAllAgentPptPlanningSources() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const payload = buildPptAllSourcesFullExportPayload(state)
      const filename = buildPptAllSourcesFullExportFilename()
      downloadJsonFile(payload, filename)
      return { filename, payload }
    },
    async deleteAgentPptPlanningSourceRecord(source = {}, sourceId = '') {
      const id = asText(sourceId || (source && source.id))
      if (!id) return null
      if (isPptDocumentSource(source)) {
        const documentId = documentIdFromPptSource(source)
        if (documentId) return this.requestAgentPptPlanningDocumentDelete(documentId)
        return null
      }
      if (isPptImageSource(source)) {
        const attachmentId = imageAttachmentIdFromPptSource(source)
        const conversationId = imageConversationIdFromPptSource(source)
        if (attachmentId && conversationId) return this.requestAgentPptPlanningImageDelete(attachmentId, conversationId)
        return null
      }
      if (isPptPersistedArtifactSource(source)) {
        const context = this.buildAgentPptPlanningApiContext ? this.buildAgentPptPlanningApiContext() : {}
        const areaId = asText((source && source.meta && (source.meta.areaId || source.meta.area_id)) || context.areaId || context.area_id)
        if (areaId) return this.requestAgentPptPlanningPersistedSourceDelete(areaId, id)
      }
      return null
    },
    async removeAgentPptPlanningSource(sourceId = '') {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const id = asText(sourceId)
      const source = cloneArray(state.sources).find((item) => asText(item && item.id) === id)
      try {
        await this.deleteAgentPptPlanningSourceRecord(source, id)
        this.updateAgentActivePptPlanningStateWithSourceStale(removePptSource(state, id), state, [id])
      } catch (error) {
        this.updateAgentActivePptPlanningState(setPptGenerationError(state, error && error.message, 'source_refresh'))
      }
    },
    async removeSelectedAgentPptPlanningSources(payload = {}) {
      const resolve = typeof payload.resolve === 'function' ? payload.resolve : null
      if (this.agentPptPlanningSourceDeleting) {
        if (resolve) resolve({ deleted: 0, failed: 0 })
        return
      }
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const requestedIds = new Set(cloneArray(payload.source_ids || payload.sourceIds).map((item) => asText(item)).filter(Boolean))
      const deletableSources = cloneArray(state.sources).filter((source) => (
        source
        && requestedIds.has(asText(source.id))
        && (isPptDocumentSource(source) || isPptImageSource(source) || isPptPersistedArtifactSource(source))
      ))
      if (!deletableSources.length) {
        if (resolve) resolve({ deleted: 0, failed: 0 })
        return
      }
      this.agentPptPlanningSourceDeleting = true
      try {
        const results = await Promise.allSettled(deletableSources.map(async (source) => {
          const sourceId = asText(source && source.id)
          await this.deleteAgentPptPlanningSourceRecord(source, sourceId)
          return sourceId
        }))
        const deletedIds = []
        const failures = []
        results.forEach((result, index) => {
          const source = deletableSources[index]
          const sourceId = asText(source && source.id)
          if (result.status === 'fulfilled') {
            deletedIds.push(sourceId)
          } else {
            failures.push({
              sourceId,
              message: asText(result.reason && result.reason.message) || asText(result.reason) || 'delete_failed',
            })
          }
        })
        let nextState = state
        deletedIds.forEach((sourceId) => {
          nextState = removePptSource(nextState, sourceId)
        })
        if (deletedIds.length) {
          nextState = markPptDirectiveStaleForSources(nextState, deletedIds)
        }
        if (failures.length) {
          const first = failures[0]
          const message = `批量删除部分失败：${failures.length} 个来源未删除（${first.sourceId || '来源'}：${first.message}）`
          nextState = setPptGenerationError(nextState, message, 'source_refresh')
        }
        this.updateAgentActivePptPlanningState(nextState)
        if (resolve) resolve({ deleted: deletedIds.length, failed: failures.length })
      } finally {
        this.agentPptPlanningSourceDeleting = false
      }
    },
    renameAgentPptPlanningSourceGroup(groupId = '', title = '') {
      this.updateAgentActivePptPlanningState(renamePptSourceGroup(this.getAgentPptPlanningStateWithSystemSources(), groupId, title))
    },
    setAgentPptPlanningSourceGroupEmoji(groupId = '', emoji = '') {
      this.updateAgentActivePptPlanningState(setPptSourceGroupEmoji(this.getAgentPptPlanningStateWithSystemSources(), groupId, emoji))
    },
    removeAgentPptPlanningSourceGroup(groupId = '') {
      this.updateAgentActivePptPlanningState(removePptSourceGroup(this.getAgentPptPlanningStateWithSystemSources(), groupId))
    },
    toggleAllAgentPptPlanningSources() {
      const summary = this.getAgentPptPlanningSourceSummary()
      const state = this.getAgentPptPlanningStateWithSystemSources()
      this.updateAgentActivePptPlanningStateWithSourceStale(setAllPptSourcesSelected(state, summary.selected < summary.ready), state)
    },
    updateAgentPptPlanningSpecField(field = '', value = '') {
      this.updateAgentActivePptPlanningState(setPptSpecField(this.getAgentPptPlanningStateWithSystemSources(), field, value))
    },
  }
}
