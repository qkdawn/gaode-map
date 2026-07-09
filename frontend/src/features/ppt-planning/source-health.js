import {
  asText,
  cloneArray,
  cloneObject,
} from './base.js'
import { normalizePptSource } from './model.js'
import { evidenceNodesFromAiPayload } from '../analysis-sources/evidence-nodes.js'

export function aiPayloadFromSource(source = {}) {
  const meta = cloneObject(source.meta)
  const payload = cloneObject(meta.aiPayload || meta.ai_payload)
  return payload.version === 'ppt_ai_input_block_v1' ? payload : {}
}

export function sourceHasDeliverableAiPayload(source = {}) {
  const aiPayload = aiPayloadFromSource(source)
  if (evidenceNodesFromAiPayload(aiPayload).length) return true
  return cloneArray(aiPayload.included).map((item) => asText(item)).filter(Boolean).length > 0
}

export function getPptSourceHealth(source = {}) {
  const normalized = normalizePptSource(source)
  const meta = cloneObject(normalized.meta)
  const status = asText(normalized.status)
  const availability = asText(normalized.availability)
  if (status === 'failed') {
    return {
      healthStatus: 'failed',
      healthLabel: '构建失败',
      healthReason: asText(meta.error || normalized.summary || meta.label) || '来源构建失败，可重试或删除后重新添加。',
      availability: 'unavailable',
      retryable: true,
    }
  }
  if (status === 'generating') {
    return {
      healthStatus: 'building',
      healthLabel: '构建中',
      healthReason: asText(normalized.summary || meta.label) || '来源正在解析或构建证据。',
      availability: 'building',
      retryable: false,
    }
  }
  if (status !== 'ready') {
    return {
      healthStatus: 'pending',
      healthLabel: '待构建',
      healthReason: asText(normalized.summary || meta.label) || '来源尚未完成构建。',
      availability: 'pending',
      retryable: false,
    }
  }
  if (availability && availability !== 'available') {
    return {
      healthStatus: 'unavailable',
      healthLabel: '不可用',
      healthReason: availability,
      availability,
      retryable: true,
    }
  }
  if (!sourceHasDeliverableAiPayload(normalized)) {
    return {
      healthStatus: 'empty_evidence',
      healthLabel: '证据为空',
      healthReason: '来源已就绪，但没有可发送给 AI 的证据或指标。',
      availability: 'empty_evidence',
      retryable: true,
    }
  }
  return {
    healthStatus: 'available',
    healthLabel: '可用于 AI',
    healthReason: '',
    availability: 'available',
    retryable: false,
  }
}
