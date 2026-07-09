import { asText, cloneObject } from './normalizers.js'

export function normalizePptGenerationErrorMessage(error = null, source = '') {
  const detail = error && error.data && typeof error.data.detail === 'object' && error.data.detail
    ? error.data.detail
    : error && error.detail && typeof error.detail === 'object'
      ? error.detail
      : null
  if (detail && asText(detail.code) === 'invalid_deck_brief_slide') {
    const pageNo = Number(detail.page_no || detail.pageNo || 0) || 0
    const reason = asText(detail.reason)
    const reasonText = reason === 'missing_required_brief_content'
      ? 'AI 返回内容不完整'
      : 'AI 返回内容未通过 brief 校验'
    return `第 ${pageNo || '当前'} 页 brief 校验失败：${reasonText}，已停止在当前页，请点击继续重试。`
  }
  if (detail && asText(detail.code) === 'ppt_planning_llm_invalid_response') {
    const pageNo = Number(detail.page_no || detail.pageNo || 0) || 0
    const jsonError = detail.json_error && typeof detail.json_error === 'object' ? detail.json_error : {}
    const line = Number(jsonError.line || 0) || 0
    const column = Number(jsonError.column || 0) || 0
    const retryText = detail.retried ? '已自动修复/重试后仍失败' : '已停止在当前页'
    const location = line && column ? `（JSON 第 ${line} 行第 ${column} 列）` : ''
    return `第 ${pageNo || '当前'} 页 brief JSON 格式错误${location}，${retryText}，请点击继续重试。`
  }
  if (asText(error && error.code) === 'ppt_slide_request_timeout') {
    const pageNo = Number(error && error.pageNo || error && error.page_no || 0) || 0
    return `第 ${pageNo || '当前'} 页请求超时，后端可能仍在处理，请点击继续重试。`
  }
  const rawDetail = error && error.data && typeof error.data.detail === 'string'
    ? error.data.detail
    : ''
  const raw = asText(error && error.message ? error.message : error)
  if (raw === 'ppt_slide_response_index_mismatch' || asText(error && error.code) === 'ppt_slide_response_index_mismatch') {
    const mismatch = error && error.detail && typeof error.detail === 'object' ? error.detail : {}
    const pageNo = Number(mismatch.pageNo || mismatch.page_no || 0) || 0
    const responseIndex = Number(mismatch.responseIndex || mismatch.response_index || 0) || 0
    return `第 ${pageNo || '当前'} 页 brief 返回页码异常（收到第 ${responseIndex || '未知'} 页），已停止写入，请点击继续重试。`
  }
  if (raw === 'ppt_slide_writeback_missing' || asText(error && error.code) === 'ppt_slide_writeback_missing') {
    const detail = error && error.detail && typeof error.detail === 'object' ? error.detail : {}
    const pageNo = Number(detail.pageNo || detail.page_no || 0) || 0
    return `第 ${pageNo || '当前'} 页已返回但未写入前端状态，已停止在当前页，请点击继续重试。`
  }
  if (raw === 'ppt_slide_writeback_lost_after_sync' || asText(error && error.code) === 'ppt_slide_writeback_lost_after_sync') {
    const detail = error && error.detail && typeof error.detail === 'object' ? error.detail : {}
    const pageNo = Number(detail.pageNo || detail.page_no || 0) || 0
    return `第 ${pageNo || '当前'} 页 brief 写入后被同步覆盖，已停止在当前页，请点击继续重试。`
  }
  const type = asText(source)
  const messages = {
    ppt_outline_llm_timeout: '目录生成超时，请稍后重试或减少来源数量。',
    ppt_planning_llm_timeout: 'AI 接口响应超时，请稍后重试。',
    ppt_outline_invalid_response: 'AI 返回的目录格式不完整，请重试。',
    invalid_ppt_outline: 'AI 返回的目录为空或格式不正确，请重试。',
    ppt_planning_invalid_ai_response: 'AI 返回内容不符合要求，请重试。',
    ppt_planning_llm_invalid_response: 'AI 返回的单页 brief 不是合法 JSON，已停止在当前页，请点击继续重试。',
    ppt_planning_llm_http_error: 'AI 接口返回错误，请稍后重试。',
    ppt_planning_llm_request_failed: 'AI 接口请求失败，请检查网络或接口配置。',
    ppt_planning_llm_unavailable: 'AI 接口未启用或配置不可用。',
    searxng_base_url_required: '本地搜索服务未启动，请用一键脚本启动或检查 SearXNG。',
    searxng_unavailable: '本地搜索服务暂不可用，请检查 8004 端口。',
  }
  return messages[rawDetail] || messages[raw] || rawDetail || raw || 'PPT 生成失败，请稍后重试。'
}
