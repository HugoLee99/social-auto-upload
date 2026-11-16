<template>
  <main class="workbench-shell">
    <header class="topbar">
      <div class="brand-block">
        <div class="brand-mark">SAU</div>
        <div>
          <p class="eyebrow">CREATOR OPERATIONS</p>
          <h1>发布控制台</h1>
        </div>
      </div>

      <div class="route-line" aria-label="发布流程">
        <div v-for="(step, index) in steps" :key="step" class="route-step" :class="{ active: index <= activeStep }">
          <span>{{ String(index + 1).padStart(2, '0') }}</span>
          <em>{{ step }}</em>
        </div>
      </div>

      <div class="monitor-state" :class="backendOnline ? 'online' : 'offline'">
        <i></i>
        <div><b>{{ backendOnline ? '检测器运行中' : '检测器离线' }}</b><small>{{ monitorText }}</small></div>
      </div>
    </header>

    <section class="workspace">
      <aside class="account-rail">
        <div class="section-heading">
          <div><p class="eyebrow">CONNECTIONS</p><h2>账号联通</h2></div>
          <button class="icon-button" title="添加账号" @click="showAccountForm = !showAccountForm">＋</button>
        </div>

        <form v-if="showAccountForm" class="account-form" @submit.prevent="addAccount">
          <select v-model="newAccount.platform" aria-label="平台">
            <option v-for="(info, key) in platforms" :key="key" :value="key">{{ info.name }}</option>
          </select>
          <input v-model.trim="newAccount.alias" placeholder="账号别名，如 creator" aria-label="账号别名" />
          <button class="small-primary" :disabled="busy">加入监控</button>
        </form>

        <div class="account-summary">
          <span><b>{{ connectedCount }}</b> / {{ accounts.length }}</span>
          <small>账号当前联通</small>
          <div class="summary-bar"><i :style="{ width: connectionPercent + '%' }"></i></div>
        </div>

        <div class="account-list">
          <article v-for="account in accounts" :key="account.platform + account.alias"
                   class="account-row" :class="account.status">
            <button class="account-select" :class="{ selected: isTarget(account) }" @click="toggleTarget(account)"
                    :disabled="account.status !== 'connected'" :aria-label="`选择 ${account.platform_name}`">
              <span class="platform-glyph">{{ platformGlyph(account.platform) }}</span>
              <span class="account-copy">
                <b>{{ account.platform_name }}</b>
                <small>@{{ account.alias }}</small>
              </span>
              <span class="status-dot" :title="statusText(account.status)"></span>
            </button>
            <div class="account-meta">
              <span>{{ statusText(account.status) }}</span>
              <time>{{ relativeTime(account.last_checked) }}</time>
              <div class="row-actions">
                <button @click="checkAccount(account)" :disabled="account.status === 'checking'">检测</button>
                <button @click="loginAccount(account)">{{ account.status === 'connected' ? '刷新登录' : '登录' }}</button>
              </div>
            </div>
          </article>

          <div v-if="!accounts.length" class="empty-accounts">
            <span>∅</span><b>还没有账号</b><small>添加平台与别名后，工作台会持续检测登录状态。</small>
          </div>
        </div>
      </aside>

      <section class="composer">
        <div class="composer-head">
          <div><p class="eyebrow">NEW DISTRIBUTION</p><h2>准备一条新内容</h2></div>
          <div class="draft-state"><span></span>{{ currentTask ? '草稿已保存' : '本地草稿' }}</div>
        </div>

        <div class="compose-grid">
          <section class="media-column">
            <label class="drop-zone" :class="{ filled: videoFile }">
              <input type="file" accept="video/*" @change="pickVideo" />
              <template v-if="videoFile">
                <div class="file-seal">VIDEO</div>
                <b>{{ videoFile.name }}</b>
                <small>{{ formatBytes(videoFile.size) }} · 点击替换</small>
              </template>
              <template v-else>
                <div class="upload-arrow">↥</div>
                <b>放入主视频</b>
                <small>MP4 / MOV / WEBM，最大 4GB</small>
              </template>
            </label>

            <div class="cover-stack">
              <label class="cover-zone">
                <input type="file" accept="image/png,image/jpeg,image/webp" @change="pickCover" />
                <span class="cover-preview landscape" :style="coverUrl ? { backgroundImage: `url(${coverUrl})` } : {}">{{ coverUrl ? '' : '＋' }}</span>
                <span><b>{{ coverFile ? coverFile.name : '添加通用封面' }}</b><small>用于 B站、YouTube、Instagram 等平台</small></span>
              </label>
              <label class="cover-zone portrait-cover">
                <input type="file" accept="image/png,image/jpeg,image/webp" @change="pickPortraitCover" />
                <span class="cover-preview portrait" :style="portraitCoverUrl ? { backgroundImage: `url(${portraitCoverUrl})` } : {}">{{ portraitCoverUrl ? '' : '＋' }}</span>
                <span><b>{{ portraitCoverFile ? portraitCoverFile.name : '添加竖屏封面' }}</b><small>建议 3:4；传给抖音、视频号，小红书可回退使用</small></span>
              </label>
            </div>

            <div class="target-strip">
              <p>本次分发到</p>
              <div v-if="selectedTargets.length" class="target-chips">
                <button v-for="target in selectedTargets" :key="target.platform + target.alias" @click="toggleTarget(target)">
                  {{ platformGlyph(target.platform) }} {{ target.platform_name }} <span>×</span>
                </button>
              </div>
              <small v-else>请点击左侧“已联通”的账号卡片进行选择</small>
            </div>
          </section>

          <form class="content-form" @submit.prevent="saveDraft">
            <label class="field wide"><span>标题 <em>{{ form.title.length }}/100</em></span>
              <input v-model="form.title" maxlength="100" placeholder="一句清楚、有力的标题" />
            </label>
            <label class="field wide"><span>正文描述</span>
              <textarea v-model="form.description" rows="7" placeholder="介绍内容、补充背景，也可以先写一个通用版本…"></textarea>
            </label>
            <label class="field wide"><span>话题标签</span>
              <input v-model="form.tags" placeholder="AI工具, 内容创作, 效率（用逗号分隔）" />
            </label>
            <div class="field-row">
              <label class="field"><span>发布时间</span>
                <select v-model="form.publishMode"><option value="now">审核后立即</option><option value="schedule">定时发布</option></select>
              </label>
              <label v-if="form.publishMode === 'schedule'" class="field"><span>定时时间</span>
                <input v-model="form.schedule" type="datetime-local" />
              </label>
              <label v-if="hasBilibili" class="field"><span>B站投稿分区</span>
                <input v-model.number="form.bilibili_tid" type="number" min="1" list="bilibili-zones" placeholder="例如 21" />
                <datalist id="bilibili-zones"><option value="21">日常</option><option value="138">搞笑</option><option value="250">出行</option><option value="161">手工</option><option value="206">资讯·综合</option><option value="249">足球</option></datalist>
                <small class="field-help">ID 是 B 站投稿分类编号，例如“日常”是 21。必须按内容选择，也可直接输入其他编号。</small>
              </label>
              <label v-if="hasYoutube" class="field"><span>YouTube 可见性</span>
                <select v-model="form.youtube_visibility"><option value="public">公开</option><option value="unlisted">不公开列出</option><option value="private">私享</option></select>
              </label>
            </div>

            <label class="runtime-toggle">
              <input v-model="form.headed" type="checkbox" />
              <span><b>可视浏览器发布</b><small>发布时弹出平台窗口，可以直接观察自动化操作到哪一步。</small></span>
            </label>

            <div class="safety-note"><span>!</span><p><b>保存不会发布。</b> 工作台会先生成核对清单，只有你在下一步明确确认后才会逐个平台执行。</p></div>
            <div class="readiness" :class="{ ready: canSave }">
              <span :class="{ done: videoFile }">{{ videoFile ? '✓' : '1' }} 视频</span>
              <span :class="{ done: form.title.trim() }">{{ form.title.trim() ? '✓' : '2' }} 标题</span>
              <span :class="{ done: selectedTargets.length }">{{ selectedTargets.length ? '✓' : '3' }} 发布账号</span>
            </div>
            <button class="review-button" :disabled="busy">
              <span>{{ busy ? '正在保存…' : '保存并进入发布核对' }}</span><i>→</i>
            </button>
          </form>
        </div>
      </section>

      <aside class="activity-rail">
        <div class="section-heading"><div><p class="eyebrow">ACTIVITY</p><h2>任务轨迹</h2></div><button class="text-button" @click="loadTasks">刷新</button></div>
        <div v-if="currentTask" class="review-panel">
          <p class="eyebrow">READY TO REVIEW</p>
          <h3>{{ currentTask.title }}</h3>
          <div class="review-status" :class="currentTask.status"><span></span><b>{{ taskStatus(currentTask.status) }}</b></div>
          <p class="status-evidence" :class="currentTask.status">{{ taskEvidence(currentTask) }}</p>

          <div class="review-targets">
            <div class="review-label">发布目标 · {{ currentTask.targets.length }}</div>
            <article v-for="target in currentTask.targets" :key="target.platform + target.alias">
              <span class="platform-glyph">{{ platformGlyph(target.platform) }}</span>
              <div><b>{{ platformName(target.platform) }}</b><small>@{{ target.alias }}</small></div>
              <em :class="targetDisplayStatus(currentTask, target)">{{ targetDisplayText(currentTask, target) }}</em>
            </article>
          </div>

          <dl class="review-facts">
            <div><dt>视频</dt><dd :title="currentTask.video_name">{{ currentTask.video_name }}</dd></div>
            <div><dt>发布时间</dt><dd>{{ currentTask.schedule || '确认后立即发布' }}</dd></div>
            <div><dt>标签</dt><dd>{{ currentTask.tags || '未填写' }}</dd></div>
            <div><dt>通用封面</dt><dd>{{ currentTask.cover_name || '未设置' }}</dd></div>
            <div><dt>竖屏封面</dt><dd>{{ currentTask.cover_portrait_name || '未设置' }}</dd></div>
            <div><dt>操作窗口</dt><dd>{{ currentTask.headed ? '可见浏览器' : '后台运行' }}</dd></div>
            <div v-if="currentTask.targets.some(t => t.platform === 'bilibili')"><dt>B站分区</dt><dd>{{ currentTask.bilibili_tid }}</dd></div>
            <div v-if="currentTask.targets.some(t => t.platform === 'youtube')"><dt>YouTube</dt><dd>{{ visibilityText(currentTask.youtube_visibility) }}</dd></div>
          </dl>
          <div v-if="currentTask.description" class="review-description"><span>正文预览</span><p>{{ currentTask.description }}</p></div>

          <section v-if="currentTask.status !== 'draft' && currentTask.results?.length" class="publish-observer">
            <div class="observer-head"><b>发布进度</b><span>{{ currentTask.headed ? '可视窗口' : '后台模式' }}</span></div>
            <div class="phase-track">
              <div v-for="(phase, index) in publishPhases" :key="phase.key" :class="phaseClass(phase.key, index)">
                <i>{{ index + 1 }}</i><span>{{ phase.label }}</span>
              </div>
            </div>
            <div class="live-logs">
              <article v-for="entry in taskLogs" :key="entry.platform + entry.alias">
                <header><b>{{ platformName(entry.platform) }} @{{ entry.alias }}</b><span>{{ phaseLabel(entry.phase) }}</span></header>
                <pre>{{ entry.text || '等待第一条运行日志…' }}</pre>
                <a v-if="entry.screenshot_url" :href="entry.screenshot_url" target="_blank">查看失败页面截图 ↗</a>
              </article>
            </div>
          </section>

          <button v-if="['queued', 'publishing', 'stopping'].includes(currentTask.status) || (currentTask.status === 'partial' && currentTask.results?.some(r => r.pid))" class="stop-button" :disabled="busy || currentTask.status === 'stopping'" @click="stopCurrent">
            {{ currentTask.status === 'stopping' ? '正在停止…' : currentTask.status === 'partial' ? '清理可能残留的上传进程' : '停止当前任务' }}
          </button>

          <template v-if="currentTask.status === 'draft'">
            <label class="confirm-check"><input v-model="publishConfirmed" type="checkbox" /><span>我已核对上述平台、账号、素材和发布时间</span></label>
            <button class="publish-button" :disabled="!publishConfirmed || busy" @click="publishCurrent">确认开始发布</button>
          </template>
          <template v-else-if="currentTask.status === 'verification_required'">
            <div v-if="currentTask.verification" class="verification-result" :class="currentTask.verification.status">
              <b>{{ verificationStatus(currentTask.verification.status) }}</b>
              <p>{{ currentTask.verification.message }}</p>
              <time>{{ relativeTime(currentTask.verification.checked_at) }}</time>
            </div>
            <div class="verification-actions">
              <button class="verify-button" :disabled="busy || currentTask.verification?.status === 'checking'" @click="verifyCurrent">自动复查</button>
              <button class="open-review-button" :disabled="busy" @click="openReview">打开抖音作品管理</button>
            </div>
            <button v-if="currentTask.verification?.status === 'not_found'" class="retry-button" :disabled="busy" @click="createRetryDraft">停止旧流程并生成重试草稿</button>
            <p class="task-locked">复查只查询原作品，不会重新上传。只有查到平台成功证据才会改成“发布成功”。</p>
          </template>
          <p v-else class="task-locked">任务已经开始，核对信息仅供查看，不能重复发布。</p>
        </div>

        <div class="timeline">
          <article v-for="task in tasks" :key="task.id" :class="task.status" @click="selectTask(task)">
            <i></i><div><b>{{ task.title }}</b><span>{{ task.targets.length }} 个平台 · {{ taskStatus(task.status) }}</span><time>{{ relativeTime(task.created_at) }}</time></div>
          </article>
          <div v-if="!tasks.length" class="empty-tasks">任务保存后，会在这里留下完整轨迹。</div>
        </div>
      </aside>
    </section>

    <div v-if="toast.message" class="toast" :class="toast.type">{{ toast.message }}</div>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

const API = '/api'
const steps = ['素材', '文案', '平台', '核对', '发布']
const platforms = ref({})
const accounts = ref([])
const tasks = ref([])
const selectedKeys = ref([])
const backendOnline = ref(false)
const monitorInterval = ref(120)
const showAccountForm = ref(false)
const busy = ref(false)
const videoFile = ref(null)
const coverFile = ref(null)
const coverUrl = ref('')
const portraitCoverFile = ref(null)
const portraitCoverUrl = ref('')
const currentTask = ref(null)
const publishConfirmed = ref(false)
const taskLogs = ref([])
const publishPhases = ref([
  { key: 'checking', label: '校验账号' }, { key: 'opening', label: '打开平台' },
  { key: 'uploading', label: '上传视频' }, { key: 'editing', label: '填写文案' },
  { key: 'cover', label: '设置封面' }, { key: 'submitting', label: '点击发布' },
  { key: 'receipt', label: '等待回执' }
])
const toast = reactive({ message: '', type: 'ok' })
const newAccount = reactive({ platform: 'xiaohongshu', alias: '' })
const form = reactive({ title: '', description: '', tags: '', publishMode: 'now', schedule: '', bilibili_tid: 21, youtube_visibility: 'public', headed: true })
let poller

const connectedCount = computed(() => accounts.value.filter(a => a.status === 'connected').length)
const connectionPercent = computed(() => accounts.value.length ? connectedCount.value / accounts.value.length * 100 : 0)
const selectedTargets = computed(() => accounts.value.filter(a => selectedKeys.value.includes(keyOf(a))))
const canSave = computed(() => videoFile.value && form.title.trim() && selectedTargets.value.length)
const hasBilibili = computed(() => selectedTargets.value.some(a => a.platform === 'bilibili'))
const hasYoutube = computed(() => selectedTargets.value.some(a => a.platform === 'youtube'))
const activeStep = computed(() => currentTask.value ? (currentTask.value.status === 'draft' ? 3 : 4) : selectedTargets.value.length ? 2 : videoFile.value ? 1 : 0)
const monitorText = computed(() => backendOnline.value ? `后台每 ${Math.round(monitorInterval.value / 60)} 分钟复检` : '请启动本地服务')

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`)
  return data
}

function notify(message, type = 'ok') { toast.message = message; toast.type = type; window.setTimeout(() => { if (toast.message === message) toast.message = '' }, 3200) }
function keyOf(a) { return `${a.platform}:${a.alias}` }
function isTarget(a) { return selectedKeys.value.includes(keyOf(a)) }
function toggleTarget(a) { const key = keyOf(a); selectedKeys.value = isTarget(a) ? selectedKeys.value.filter(v => v !== key) : [...selectedKeys.value, key] }
function platformGlyph(p) { return ({ xiaohongshu: 'RED', douyin: 'DY', tencent: 'WX', bilibili: 'B', youtube: 'YT', instagram: 'IG' })[p] || p.slice(0, 2).toUpperCase() }
function statusText(s) { return ({ connected: '已联通', disconnected: '需登录', checking: '检测中', error: '连接异常', unknown: '待检测', login_required: '等待登录' })[s] || s }
function taskStatus(s) { return ({ draft: '待确认', queued: '已排队', publishing: '发布流程运行中', stopping: '正在停止', stopped: '已停止', completed: '全部发布成功', partial: '部分失败', verification_required: '结果未知 · 需平台核验', cancelled_for_retry: '旧流程已停止' })[s] || s }
function taskEvidence(task) { return ({ draft: task.retry_of ? '这是重试草稿；请重新核对后再确认发布。' : '尚未启动发布，勾选确认后才会执行。', queued: '任务已进入队列，但还没有平台成功证据。', publishing: '请查看下方阶段和实时日志；运行中不等于发布成功。', stopping: '正在终止该任务对应的浏览器和上传进程。', stopped: task.message || '任务已停止；如果此前已经提交，请仍到平台作品管理核对。', completed: '所有目标平台都已返回成功结果。', partial: '至少一个平台返回失败，请查看阶段、日志和失败截图。', verification_required: task.message || '工作台未收到最终回执，请到平台作品管理核对，勿直接重发。', cancelled_for_retry: '此任务的旧上传流程已停止，请使用新生成的重试草稿。' })[task.status] || '等待状态更新。' }
function verificationStatus(s) { return ({ checking: '正在查询平台', published: '平台已确认发布', found: '找到作品，状态待确认', not_found: '暂未找到作品', error: '自动复查失败' })[s] || s }
function platformName(platform) { return platforms.value[platform]?.name || platform }
function visibilityText(value) { return ({ public: '公开', unlisted: '不公开列出', private: '私享' })[value] || value || '公开' }
function matchingResult(task, target) { return (task.results || []).find(r => r.platform === target.platform && r.alias === target.alias) }
function targetDisplayStatus(task, target) { return matchingResult(task, target)?.status || accounts.value.find(a => keyOf(a) === keyOf(target))?.status || 'unknown' }
function targetDisplayText(task, target) { const result = matchingResult(task, target); return result ? ({ checking: '发布前检查', publishing: phaseLabel(result.phase), success: '发布成功', failed: '发布失败', stopped: '已停止', verification_required: '需平台核验' })[result.status] || result.status : statusText(targetDisplayStatus(task, target)) }
function phaseLabel(key) { return ({ checking: '校验账号', opening: '打开平台', uploading: '上传视频', editing: '填写文案', cover: '设置封面', submitting: '点击发布', receipt: '等待回执', success: '发布成功', failed: '发布失败', stopped: '已停止' })[key] || '准备中' }
function activePhase() { return taskLogs.value.find(item => item.status === 'publishing')?.phase || taskLogs.value.at(-1)?.phase || 'checking' }
function phaseClass(key, index) { const current = activePhase(); const currentIndex = publishPhases.value.findIndex(item => item.key === current); return { active: key === current, done: current === 'success' || (currentIndex >= 0 && index < currentIndex), failed: ['failed', 'stopped'].includes(current) && index === Math.max(0, currentIndex) } }
function formatBytes(n) { return n > 1073741824 ? `${(n / 1073741824).toFixed(2)} GB` : `${(n / 1048576).toFixed(1)} MB` }
function safeTransferName(file, prefix) { const match = file.name.match(/\.(jpe?g|png|webp)$/i); return `${prefix}.${match ? match[1].toLowerCase() : 'jpg'}` }
function relativeTime(value) { if (!value) return '尚未检测'; const seconds = Math.floor((Date.now() - new Date(value).getTime()) / 1000); if (seconds < 60) return '刚刚'; if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`; if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`; return new Date(value).toLocaleDateString('zh-CN') }
function pickVideo(e) { videoFile.value = e.target.files[0] || null; currentTask.value = null }
function pickCover(e) { if (coverUrl.value) URL.revokeObjectURL(coverUrl.value); coverFile.value = e.target.files[0] || null; coverUrl.value = coverFile.value ? URL.createObjectURL(coverFile.value) : '' }
async function pickPortraitCover(e) {
  if (portraitCoverUrl.value) URL.revokeObjectURL(portraitCoverUrl.value)
  const file = e.target.files[0] || null
  portraitCoverFile.value = null; portraitCoverUrl.value = ''
  if (!file) return
  try {
    const image = await createImageBitmap(file)
    const width = image.width; const height = image.height; image.close()
    if (Math.abs(width / height - 0.75) > 0.035) {
      e.target.value = ''
      return notify(`竖屏封面需要 3:4，当前是 ${width}×${height}`, 'error')
    }
    portraitCoverFile.value = file
    portraitCoverUrl.value = URL.createObjectURL(file)
    notify(`竖屏封面已通过检查：${width}×${height}`)
  } catch {
    e.target.value = ''
    notify('无法读取这张图片，请转换为 JPG、PNG 或 WebP 后重试', 'error')
  }
}

async function loadHealth() { try { const data = await api('/health'); backendOnline.value = true; monitorInterval.value = data.monitor_interval } catch { backendOnline.value = false } }
async function loadAccounts() { try { accounts.value = await api('/accounts'); backendOnline.value = true; selectedKeys.value = selectedKeys.value.filter(k => accounts.value.some(a => keyOf(a) === k && a.status === 'connected')) } catch { backendOnline.value = false } }
async function loadTaskLogs() { if (!currentTask.value || currentTask.value.status === 'draft') { taskLogs.value = []; return } try { const data = await api(`/tasks/${currentTask.value.id}/logs`); taskLogs.value = data.logs || []; if (data.phases?.length) publishPhases.value = data.phases } catch { taskLogs.value = [] } }
async function loadTasks() { try { tasks.value = await api('/tasks'); if (currentTask.value) currentTask.value = tasks.value.find(t => t.id === currentTask.value.id) || currentTask.value; await loadTaskLogs() } catch (e) { notify(e.message, 'error') } }
function selectTask(task) { currentTask.value = task; loadTaskLogs() }
async function addAccount() { if (!newAccount.alias) return notify('请填写账号别名', 'error'); busy.value = true; try { await api('/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newAccount) }); newAccount.alias = ''; showAccountForm.value = false; await loadAccounts(); notify('账号已加入持续监控') } catch (e) { notify(e.message, 'error') } finally { busy.value = false } }
async function checkAccount(a) { try { await api(`/accounts/${a.platform}/${a.alias}/check`, { method: 'POST' }); await loadAccounts() } catch (e) { notify(e.message, 'error') } }
async function loginAccount(a) { try { await api(`/accounts/${a.platform}/${a.alias}/login`, { method: 'POST' }); notify('登录窗口已打开，请在那里完成登录'); await loadAccounts() } catch (e) { notify(e.message, 'error') } }

async function saveDraft() {
  if (!videoFile.value) return notify('请先放入主视频', 'error')
  if (!form.title.trim()) return notify('请填写标题', 'error')
  if (!selectedTargets.value.length) return notify('请点击左侧已联通的账号，选择发布目标', 'error')
  busy.value = true
  try {
    const schedule = form.publishMode === 'schedule' && form.schedule ? form.schedule.replace('T', ' ') : ''
    const metadata = { ...form, schedule, targets: selectedTargets.value.map(({ platform, alias }) => ({ platform, alias })) }
    const body = new FormData(); body.append('metadata', JSON.stringify(metadata)); body.append('video', videoFile.value); if (coverFile.value) body.append('cover', coverFile.value); if (portraitCoverFile.value) body.append('cover_portrait', portraitCoverFile.value, safeTransferName(portraitCoverFile.value, 'cover-portrait'))
    currentTask.value = await api('/tasks', { method: 'POST', body }); publishConfirmed.value = false; await loadTasks(); notify('草稿已保存，请进行最终核对')
  } catch (e) { notify(e.message, 'error') } finally { busy.value = false }
}

async function publishCurrent() {
  if (!currentTask.value || !publishConfirmed.value) return
  busy.value = true
  try { await api(`/tasks/${currentTask.value.id}/publish`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) }); notify('发布任务已启动'); await loadTasks() }
  catch (e) { notify(e.message, 'error') } finally { busy.value = false }
}

async function stopCurrent() {
  if (!currentTask.value) return
  if (!window.confirm('停止后会关闭这条任务对应的自动化浏览器和上传进程。平台端已经提交的内容不会被自动撤回，是否继续？')) return
  busy.value = true
  try { await api(`/tasks/${currentTask.value.id}/stop`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) }); notify('任务已停止，请核对平台作品管理'); await loadTasks() }
  catch (e) { notify(e.message, 'error') } finally { busy.value = false }
}

async function verifyCurrent() {
  if (!currentTask.value) return
  busy.value = true
  try { await api(`/tasks/${currentTask.value.id}/verify`, { method: 'POST' }); notify('已开始只读复查，不会重新上传'); await loadTasks() }
  catch (e) { notify(e.message, 'error') } finally { busy.value = false }
}

async function openReview() {
  if (!currentTask.value) return
  busy.value = true
  try { await api(`/tasks/${currentTask.value.id}/open-review`, { method: 'POST' }); notify('正在打开抖音作品管理窗口') }
  catch (e) { notify(e.message, 'error') } finally { busy.value = false }
}

async function createRetryDraft() {
  if (!currentTask.value) return
  const confirmed = window.confirm('将终止这条任务仍在运行的旧上传进程，并复制原素材生成新的待确认草稿。不会立即重新发布。是否继续？')
  if (!confirmed) return
  busy.value = true
  try {
    const data = await api(`/tasks/${currentTask.value.id}/retry-draft`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) })
    currentTask.value = data.task; publishConfirmed.value = false; await loadTasks(); notify('旧流程已停止，请核对新草稿后再确认发布')
  } catch (e) { notify(e.message, 'error') } finally { busy.value = false }
}

onMounted(async () => { await loadHealth(); try { platforms.value = await api('/platforms') } catch {} await Promise.all([loadAccounts(), loadTasks()]); poller = window.setInterval(() => { loadAccounts(); loadTasks(); loadHealth() }, 5000) })
onBeforeUnmount(() => { window.clearInterval(poller); if (coverUrl.value) URL.revokeObjectURL(coverUrl.value); if (portraitCoverUrl.value) URL.revokeObjectURL(portraitCoverUrl.value) })
</script>
