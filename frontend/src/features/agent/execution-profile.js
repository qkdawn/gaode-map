const CAPABILITIES_URL = '/api/v1/analysis/agent/capabilities'
const MODEL_PROFILES_URL = '/api/v1/analysis/agent/model-profiles'

const text = value => String(value || '').trim()

export function slashSkillQuery(value = '') {
  const match = String(value || '').match(/^\/([^\s]*)$/u)
  return match ? match[1].toLowerCase() : null
}

export function createAgentExecutionProfileMethods() {
  return {
    async loadAgentCapabilities(force = false) {
      if (this.agentCapabilitiesLoaded && !force) return
      this.agentCapabilitiesLoading = true
      this.agentCapabilitiesError = ''
      try {
        const res = await fetch(CAPABILITIES_URL)
        if (!res.ok) throw new Error(`能力目录请求失败(${res.status})`)
        const data = await res.json()
        this.agentModels = Array.isArray(data.models) ? data.models : []
        this.agentSkills = Array.isArray(data.skills) ? data.skills.filter(item => item.executable) : []
        if (!this.agentSelectedModelProfileId) this.agentSelectedModelProfileId = text(data.default_model_profile_id)
        this.agentCapabilitiesLoaded = true
      } catch (error) {
        this.agentCapabilitiesError = error instanceof Error ? error.message : String(error)
      } finally { this.agentCapabilitiesLoading = false }
    },
    getAgentSelectedModel() {
      if (this.agentSelectedModelProfileId) {
        return this.agentModels.find(item => item.id === this.agentSelectedModelProfileId) || null
      }
      return this.agentModels.find(item => item.is_default && item.enabled) || null
    },
    getAgentSelectedModelName() {
      const model = this.getAgentSelectedModel()
      if (model) return model.display_name
      if (this.agentSelectedModelProfileId && this.agentCapabilitiesLoaded) return '模型不可用'
      return this.agentCapabilitiesLoading ? '加载模型' : '选择模型'
    },
    toggleAgentModelMenu() {
      this.agentModelMenuOpen = !this.agentModelMenuOpen
      if (this.agentModelMenuOpen) this.loadAgentCapabilities(true)
    },
    resizeAgentComposerInput(event) {
      const input = event && event.target
      if (!input || !input.style || typeof input.scrollHeight !== 'number') return
      const maxHeight = 240
      input.style.height = 'auto'
      input.style.height = `${Math.min(Math.max(input.scrollHeight, 48), maxHeight)}px`
      input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden'
    },
    selectAgentModel(profileId) {
      this.agentSelectedModelProfileId = text(profileId)
      this.agentModelMenuOpen = false
      this.persistAgentConversationExecutionProfile()
    },
    getAgentSkillMatches() {
      const query = slashSkillQuery(this.agentInput)
      if (query === null) return []
      return this.agentSkills.filter(item => `${item.id} ${item.display_name}`.toLowerCase().includes(query))
    },
    chooseAgentSkill(skill) {
      this.agentSelectedSkillId = text(skill && skill.id)
      this.agentSkillScope = 'turn'
      this.agentInput = ''
    },
    clearAgentSkill() {
      this.agentSelectedSkillId = ''
      this.agentPinnedSkillId = ''
      this.agentSkillScope = 'turn'
      this.persistAgentConversationExecutionProfile()
    },
    toggleAgentSkillScope() {
      this.agentSkillScope = this.agentSkillScope === 'conversation' ? 'turn' : 'conversation'
      this.agentPinnedSkillId = this.agentSkillScope === 'conversation' ? this.agentSelectedSkillId : ''
      this.persistAgentConversationExecutionProfile()
    },
    persistAgentConversationExecutionProfile() {
      if (typeof this.syncCurrentAgentSession !== 'function') return
      const session = this.syncCurrentAgentSession()
      if (!session || !session.persisted || typeof this.putAgentSession !== 'function') return
      const conversationExecutionProfile = {
        model_profile_id: text(this.agentSelectedModelProfileId),
        pinned_skill_id: text(this.agentPinnedSkillId),
      }
      this.putAgentSession(session.id, { conversationExecutionProfile }).catch((error) => {
        this.agentCapabilitiesError = error instanceof Error ? error.message : String(error)
      })
    },
    getAgentSelectedSkill() {
      const id = this.agentSelectedSkillId || this.agentPinnedSkillId
      return this.agentSkills.find(item => item.id === id) || null
    },
    openAgentModelConfig(profile = null) {
      this.agentModelMenuOpen = false
      this.agentModelConfigOpen = true
      this.agentModelForm = profile ? {
        id: profile.id, display_name: profile.display_name, provider: profile.provider,
        base_url: profile.base_url, model: profile.model, api_key: '', enabled: profile.enabled,
        is_default: profile.is_default, has_api_key: profile.has_api_key,
      } : { id: '', display_name: '', provider: 'openai_compatible', base_url: '', model: '', api_key: '', enabled: true, is_default: false, has_api_key: false }
      this.agentModelConfigMessage = ''
    },
    closeAgentModelConfig() { this.agentModelConfigOpen = false },
    async saveAgentModelProfile() {
      const form = this.agentModelForm || {}
      const editing = !!form.id
      const body = { display_name: form.display_name, provider: form.provider, base_url: form.base_url, model: form.model, enabled: !!form.enabled, is_default: !!form.is_default }
      if (text(form.api_key)) body.api_key = form.api_key
      const res = await fetch(editing ? `${MODEL_PROFILES_URL}/${form.id}` : MODEL_PROFILES_URL, { method: editing ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!res.ok) { const error = await res.json().catch(() => ({})); throw new Error(error.detail || `保存失败(${res.status})`) }
      const saved = await res.json()
      this.agentSelectedModelProfileId = saved.id
      await this.loadAgentCapabilities(true)
      this.persistAgentConversationExecutionProfile()
      this.openAgentModelConfig(saved)
      this.agentModelConfigMessage = '已保存'
    },
    async testAgentModelProfile() {
      const form = this.agentModelForm || {}
      const body = form.id && !text(form.api_key) ? { profile_id: form.id } : { provider: form.provider, base_url: form.base_url, model: form.model, api_key: form.api_key }
      const res = await fetch(`${MODEL_PROFILES_URL}/test`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const data = await res.json().catch(() => ({}))
      this.agentModelConfigMessage = data.message || (res.ok ? '测试完成' : '测试失败')
    },
    async deleteAgentModelProfile(profile) {
      if (!profile || profile.source === 'system') return
      const res = await fetch(`${MODEL_PROFILES_URL}/${profile.id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`删除失败(${res.status})`)
      if (this.agentSelectedModelProfileId === profile.id) this.agentSelectedModelProfileId = ''
      await this.loadAgentCapabilities(true)
      this.persistAgentConversationExecutionProfile()
      this.openAgentModelConfig()
    },
  }
}
