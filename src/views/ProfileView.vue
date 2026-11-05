<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import StatusTag from '../components/StatusTag.vue'
import DifficultyTag from '../components/DifficultyTag.vue'
import { getUserContestRecords, getUserStats } from '../api/me'
import { listSubmissions } from '../api/submissions'
import { getContest } from '../api/contests'
import { ApiError } from '../api/client'
import { changePassword as changePasswordRequest, session, updateProfile } from '../stores/session'
import { contestStatusMap, formatDate, formatDateTime, formatNumber, formatPenaltySeconds } from '../utils/format'
import type { Contest, Difficulty, Language, Submission, UserContestRecord, UserStats } from '../types'

const router = useRouter()
const profileDialogVisible = ref(false)
const passwordDialogVisible = ref(false)
const profileSaving = ref(false)
const passwordSaving = ref(false)
const loading = ref(true)
const loadError = ref('')
const profileFormRef = ref<FormInstance>()
const passwordFormRef = ref<FormInstance>()
const profileForm = reactive({ nickname: '', school: '', bio: '' })
const passwordForm = reactive({ currentPassword: '', newPassword: '', confirmPassword: '' })
const stats = ref<UserStats | null>(null)
const recentList = ref<Submission[]>([])
const contestRecords = ref<Array<UserContestRecord & { contest?: Contest }>>([])
const languageLabels: Record<Language, string> = { cpp: 'C++11', c: 'C99', java: 'JDK 8', python: 'Python 3.8.6' }

const profile = computed(() => session.profile)
const progressGroups = computed(() => (stats.value?.difficultyProgress ?? []).map(group => ({
  ...group,
  percentage: group.total ? Math.round(group.solved / group.total * 100) : 0,
})))
const totalSolved = computed(() => progressGroups.value.reduce((sum, item) => sum + item.solved, 0))
const totalProblems = computed(() => progressGroups.value.reduce((sum, item) => sum + item.total, 0))
const overallPercent = computed(() => totalProblems.value ? Math.round(totalSolved.value / totalProblems.value * 100) : 0)

const profileRules: FormRules = {
  nickname: [{ required: true, message: '请输入昵称', trigger: 'blur' }, { min: 1, max: 50, message: '昵称长度为 1–50 个字符', trigger: 'blur' }],
  school: [{ max: 100, message: '学校名称不能超过 100 个字符', trigger: 'blur' }],
  bio: [{ max: 500, message: '个人简介不能超过 500 个字符', trigger: 'blur' }],
}
const passwordRules: FormRules = {
  currentPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [{ required: true, trigger: 'blur', validator: (_rule, value, callback) => {
    if (!value) callback(new Error('请输入新密码'))
    else if (value.length < 8 || !/[A-Za-z]/.test(value) || !/\d/.test(value)) callback(new Error('至少 8 位，并同时包含字母和数字'))
    else if (value === passwordForm.currentPassword) callback(new Error('新密码不能与当前密码相同'))
    else callback()
  } }],
  confirmPassword: [{ required: true, trigger: 'blur', validator: (_rule, value, callback) => {
    if (!value) callback(new Error('请再次输入新密码'))
    else if (value !== passwordForm.newPassword) callback(new Error('两次输入的密码不一致'))
    else callback()
  } }],
}

async function loadProfileData() {
  loading.value = true
  loadError.value = ''
  try {
    const [statsData, submissions, records] = await Promise.all([
      getUserStats(),
      listSubmissions({ page: 1, pageSize: 5 }),
      getUserContestRecords(),
    ])
    stats.value = statsData
    recentList.value = submissions.items
    const contests = await Promise.all(records.map(async record => {
      try { return { ...record, contest: await getContest(record.contestId) } } catch { return record }
    }))
    contestRecords.value = contests
  } catch (error) {
    loadError.value = error instanceof ApiError ? error.message : '个人数据加载失败'
  } finally {
    loading.value = false
  }
}

function openProfileDialog() {
  if (!profile.value) return
  Object.assign(profileForm, { nickname: profile.value.nickname, school: profile.value.school, bio: profile.value.bio })
  profileDialogVisible.value = true
}

async function saveProfile() {
  if (profileSaving.value || !profileFormRef.value) return
  try { await profileFormRef.value.validate() } catch { return }
  profileSaving.value = true
  try {
    await updateProfile({ nickname: profileForm.nickname.trim(), school: profileForm.school.trim(), bio: profileForm.bio.trim() })
    profileDialogVisible.value = false
    ElMessage.success('个人资料已保存')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '资料保存失败')
  } finally { profileSaving.value = false }
}

function openPasswordDialog() {
  clearPasswordForm()
  passwordDialogVisible.value = true
}

async function changePassword() {
  if (passwordSaving.value || !passwordFormRef.value) return
  try { await passwordFormRef.value.validate() } catch { return }
  passwordSaving.value = true
  try {
    await changePasswordRequest({ oldPassword: passwordForm.currentPassword, newPassword: passwordForm.newPassword })
    passwordDialogVisible.value = false
    ElMessage.success('密码已修改，请使用新密码重新登录')
    await router.replace('/login')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '密码修改失败')
  } finally { passwordSaving.value = false }
}

function clearPasswordForm() {
  Object.assign(passwordForm, { currentPassword: '', newPassword: '', confirmPassword: '' })
  passwordFormRef.value?.clearValidate()
}

function openSubmissionProblem(submission: Submission) {
  // The workspace itself drops the contest context when the contest is not
  // ongoing, so carrying the id here is always safe.
  void router.push({
    path: `/problems/${submission.problemId}`,
    query: submission.contestId ? { contest: submission.contestId } : {},
  })
}

onMounted(loadProfileData)
</script>

<template>
  <div class="profile-page" v-loading="loading">
    <el-alert v-if="loadError" type="error" :title="loadError" show-icon :closable="false"><el-button text @click="loadProfileData">重新加载</el-button></el-alert>
    <template v-if="profile && stats">
      <section class="profile-hero surface-card">
        <div class="profile-identity">
          <div class="profile-avatar">{{ profile.nickname.slice(0, 1) }}<span><el-icon><Medal /></el-icon></span></div>
          <div class="identity-copy">
            <span class="profile-file-label">新保研学习档案</span>
            <div class="name-line"><h1>{{ profile.nickname }}</h1><span class="role-badge"><el-icon><User /></el-icon>{{ session.role === 'admin' ? '管理员' : '算法学习者' }}</span></div>
            <span class="username mono">@{{ profile.username }}</span>
            <p class="bio">{{ profile.bio || '这个人很神秘，还没有填写个人简介。' }}</p>
            <div class="profile-meta"><span><el-icon><Message /></el-icon>{{ profile.email }}</span><span><el-icon><School /></el-icon>{{ profile.school || '暂未填写学校' }}</span><span><el-icon><Calendar /></el-icon>{{ formatDate(profile.joinedAt) }} 加入</span></div>
          </div>
        </div>
        <div class="hero-side"><div class="ranking-block"><span>全站排名</span><strong>{{ stats.ranking ? `#${formatNumber(stats.ranking)}` : '尚未上榜' }}</strong><small>持续练习，超越昨天的自己</small></div><div class="profile-actions"><el-button @click="openPasswordDialog"><el-icon><Lock /></el-icon>修改密码</el-button><el-button type="primary" @click="openProfileDialog"><el-icon><Edit /></el-icon>编辑资料</el-button></div></div>
      </section>

      <section class="stat-grid profile-stats" aria-label="做题统计">
        <article class="stat-card"><div class="stat-label">通过提交<span class="stat-icon success-icon"><el-icon><CircleCheck /></el-icon></span></div><strong class="stat-value">{{ stats.acceptedCount }}</strong><div class="stat-foot">已解决 <strong>{{ stats.solvedCount }}</strong> 道不同题目</div></article>
        <article class="stat-card"><div class="stat-label">累计提交<span class="stat-icon"><el-icon><Upload /></el-icon></span></div><strong class="stat-value">{{ stats.submissionCount }}</strong><div class="stat-foot">每一行代码都是进步</div></article>
        <article class="stat-card"><div class="stat-label">提交通过率<span class="stat-icon orange-icon"><el-icon><DataAnalysis /></el-icon></span></div><strong class="stat-value">{{ stats.acceptance }}<small>%</small></strong><div class="stat-foot">不含等待、判题中和系统异常</div></article>
        <article class="stat-card streak-card"><div class="stat-label">连续学习<span class="stat-icon flame-icon"><el-icon><Sunny /></el-icon></span></div><strong class="stat-value">{{ stats.streak }}<small>天</small></strong><div class="week-dots"><i v-for="day in 7" :key="day" :class="{ active: day <= Math.min(7, stats.streak) }" /><span>明天也要继续</span></div></article>
      </section>

      <div class="profile-content-grid">
        <section class="content-card recent-card">
          <div class="section-heading"><div><h2>近期提交</h2><p>最近的判题结果与提交动态</p></div><el-button text type="primary" @click="router.push('/submissions')">查看全部<el-icon><ArrowRight /></el-icon></el-button></div>
          <div v-if="recentList.length" class="recent-list"><article v-for="submission in recentList" :key="submission.id" class="recent-item"><button class="recent-problem" @click="openSubmissionProblem(submission)"><span class="problem-symbol"><el-icon><Document /></el-icon></span><span><strong>{{ submission.problemTitle }}</strong><small class="mono">{{ submission.problemId }} · {{ languageLabels[submission.language] }}</small></span></button><span v-if="submission.contestTitle" class="contest-source"><el-icon><Trophy /></el-icon>{{ submission.contestTitle }}</span><StatusTag :status="submission.status" compact /><time>{{ formatDateTime(submission.createdAt) }}</time><el-button class="row-action" text type="primary" @click="openSubmissionProblem(submission)">查看题目</el-button></article></div>
          <div v-else class="empty-state"><h3>还没有提交记录</h3><p>从一道简单题开始你的学习之旅。</p><el-button type="primary" @click="router.push('/problems')">开始刷题</el-button></div>
        </section>

        <section class="content-card progress-card">
          <div class="section-heading"><div><h2>刷题进度</h2><p>不同难度的掌握情况</p></div><span class="solved-total"><strong>{{ totalSolved }}</strong> / {{ totalProblems }}</span></div>
          <div class="overall-progress"><div class="progress-ring" :style="{ '--progress': `${overallPercent * 3.6}deg` }"><div><strong>{{ overallPercent }}%</strong><span>总完成度</span></div></div><div class="overall-copy"><strong>保持稳定的节奏</strong><p>再完成 {{ Math.max(0, totalProblems - totalSolved) }} 题，即可达成当前题库全收集。</p><button @click="router.push('/problems')">继续刷题<el-icon><Right /></el-icon></button></div></div>
          <div class="difficulty-progress-list"><div v-for="group in progressGroups" :key="group.difficulty" class="difficulty-progress"><div class="progress-label"><DifficultyTag :difficulty="group.difficulty as Difficulty" /><span><strong>{{ group.solved }}</strong> / {{ group.total }} 题</span></div><el-progress :percentage="group.percentage" :stroke-width="7" :show-text="false" :color="group.difficulty === '简单' ? '#168a70' : group.difficulty === '中等' ? '#f29a38' : '#d95764'" /></div></div>
          <div class="progress-tip"><el-icon><Star /></el-icon>尝试不同知识点，比单纯追求数量更重要</div>
        </section>
      </div>

      <section class="content-card contest-history-card">
        <div class="section-heading"><div><h2>参赛记录</h2><p>每一次上场，都是对自己最好的检验</p></div><el-button text type="primary" @click="router.push('/contests')">发现更多竞赛<el-icon><ArrowRight /></el-icon></el-button></div>
        <div v-if="contestRecords.length" class="contest-list"><article v-for="record in contestRecords" :key="record.contestId" class="contest-item"><span class="contest-accent" /><div class="contest-main"><div class="contest-title-line"><h3>{{ record.contest?.title ?? `竞赛 #${record.contestId}` }}</h3><span v-if="record.contest" class="status-pill" :class="contestStatusMap[record.contest.status].tone"><i />{{ contestStatusMap[record.contest.status].label }}</span></div><p><span><el-icon><Calendar /></el-icon>{{ record.contest ? formatDateTime(record.contest.startTime) : formatDateTime(record.registeredAt) }}</span><span v-if="record.contest"><el-icon><User /></el-icon>{{ formatNumber(record.contest.participants) }} 人参赛</span></p></div><div class="contest-result"><small>我的排名</small><strong>{{ record.rank ? `#${record.rank}` : '—' }}</strong></div><div class="contest-result"><small>通过题数</small><strong>{{ record.solvedCount }} <em>/ {{ record.contest?.problems.length ?? '—' }}</em></strong></div><div class="contest-result penalty"><small>总罚时</small><strong>{{ formatPenaltySeconds(record.penaltySeconds) }}</strong></div><el-button v-if="record.contest" class="contest-action" @click="router.push(`/contests/${record.contestId}`)">查看比赛<el-icon><ArrowRight /></el-icon></el-button></article></div>
        <div v-else class="empty-state"><h3>还没有参赛记录</h3><p>报名一场竞赛，检验阶段性的学习成果。</p><el-button type="primary" @click="router.push('/contests')">浏览竞赛</el-button></div>
      </section>
    </template>

    <el-dialog v-model="profileDialogVisible" title="编辑个人资料" width="520px" class="profile-dialog" destroy-on-close>
      <el-form ref="profileFormRef" :model="profileForm" :rules="profileRules" label-position="top" @submit.prevent="saveProfile"><el-form-item label="登录用户名"><el-input :model-value="profile?.username" disabled /></el-form-item><el-form-item label="昵称" prop="nickname"><el-input v-model="profileForm.nickname" maxlength="50" show-word-limit /></el-form-item><el-form-item label="邮箱地址"><el-input :model-value="profile?.email" disabled><template #prefix><el-icon><Message /></el-icon></template></el-input><span class="form-tip">邮箱用于找回密码，暂不支持修改</span></el-form-item><el-form-item label="学校 / 组织" prop="school"><el-input v-model="profileForm.school" maxlength="100" /></el-form-item><el-form-item label="个人简介" prop="bio"><el-input v-model="profileForm.bio" type="textarea" :rows="3" maxlength="500" show-word-limit /></el-form-item></el-form>
      <template #footer><el-button @click="profileDialogVisible = false">取消</el-button><el-button type="primary" :loading="profileSaving" @click="saveProfile">保存修改</el-button></template>
    </el-dialog>
    <el-dialog v-model="passwordDialogVisible" title="修改登录密码" width="460px" class="profile-dialog" destroy-on-close @closed="clearPasswordForm">
      <div class="password-notice"><el-icon><Lock /></el-icon><span>修改成功后所有会话将退出，需要使用新密码重新登录。</span></div>
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-position="top" @submit.prevent="changePassword"><el-form-item label="当前密码" prop="currentPassword"><el-input v-model="passwordForm.currentPassword" type="password" show-password autocomplete="current-password" /></el-form-item><el-form-item label="新密码" prop="newPassword"><el-input v-model="passwordForm.newPassword" type="password" show-password autocomplete="new-password" /></el-form-item><el-form-item label="确认新密码" prop="confirmPassword"><el-input v-model="passwordForm.confirmPassword" type="password" show-password autocomplete="new-password" /></el-form-item></el-form>
      <template #footer><el-button @click="passwordDialogVisible = false">取消</el-button><el-button type="primary" :loading="passwordSaving" @click="changePassword">确认修改</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.profile-page{color:var(--text)}.profile-hero{position:relative;overflow:hidden;min-height:216px;padding:31px 34px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;gap:28px;background:#fff;border-top:4px solid var(--primary);border-radius:10px}.profile-identity{display:flex;align-items:center;gap:24px;min-width:0}.profile-avatar{position:relative;flex:none;width:96px;height:96px;border-radius:22px;display:grid;place-items:center;background:var(--primary);color:#fff;font-size:36px}.profile-avatar>span{position:absolute;right:-5px;bottom:-5px;width:29px;height:29px;display:grid;place-items:center;border-radius:50%;border:3px solid #fff;color:#b86c1c;background:var(--accent-soft)}.profile-file-label{color:var(--primary);font-size:10px;font-weight:600}.name-line{display:flex;align-items:center;gap:11px}.name-line h1{margin:5px 0;color:var(--text-strong);font-size:27px}.role-badge{display:inline-flex;gap:4px;color:var(--primary);background:var(--primary-soft);padding:4px 8px;border-radius:5px;font-size:9px}.username{color:var(--text-tertiary);font-size:11px}.bio{color:var(--text-secondary);max-width:560px;font-size:12px}.profile-meta{display:flex;flex-wrap:wrap;gap:8px 18px;color:var(--text-tertiary);font-size:10px}.profile-meta span{display:inline-flex;align-items:center;gap:5px}.hero-side{display:flex;flex-direction:column;align-items:flex-end;gap:23px}.ranking-block{display:flex;flex-direction:column;align-items:flex-end}.ranking-block strong{font-size:25px}.ranking-block span,.ranking-block small{color:var(--text-tertiary);font-size:9px}.profile-actions{display:flex;gap:9px}.profile-stats{margin:20px 0}.stat-value small{font-size:13px}.success-icon{color:var(--success)!important}.profile-content-grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(310px,.8fr);gap:20px}.content-card{background:#fff;border:1px solid var(--border);border-radius:10px;padding:20px}.recent-card,.progress-card{min-height:400px}.recent-item{display:flex;align-items:center;gap:15px;padding:13px 8px;border-bottom:1px solid #e9eff7}.recent-problem{display:flex;align-items:center;gap:10px;flex:1;min-width:150px;text-align:left;border:0;background:transparent;cursor:pointer}.recent-problem>span:last-child{display:flex;flex-direction:column}.problem-symbol{width:32px;height:32px;display:grid;place-items:center;border-radius:7px;background:var(--primary-soft);color:var(--primary)}.recent-problem strong{font-size:12px}.recent-problem small,.recent-item>time{color:var(--text-tertiary);font-size:9px}.contest-source{max-width:115px;color:var(--text-tertiary);font-size:9px}.solved-total strong{color:var(--primary);font-size:18px}.overall-progress{display:flex;align-items:center;gap:18px;padding:16px 0 23px}.progress-ring{--progress:0deg;width:94px;height:94px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--primary) var(--progress),#e5edf6 0);position:relative}.progress-ring:before{content:'';position:absolute;inset:8px;border-radius:50%;background:#fff}.progress-ring>div{position:relative;text-align:center}.progress-ring strong{font-size:18px}.progress-ring span{display:block;font-size:8px}.overall-copy p{color:var(--text-secondary);font-size:10px}.overall-copy button{border:0;background:none;color:var(--primary);cursor:pointer}.difficulty-progress{margin-bottom:16px}.progress-label{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}.progress-tip{padding:10px;border-radius:7px;background:var(--accent-soft);font-size:9px}.contest-history-card{margin-top:20px}.contest-item{position:relative;display:flex;align-items:center;gap:25px;padding:19px 20px 19px 24px;border-bottom:1px solid var(--border)}.contest-accent{position:absolute;left:0;top:16px;bottom:16px;width:3px;background:var(--primary)}.contest-main{flex:1;min-width:250px}.contest-title-line{display:flex;align-items:center;gap:10px}.contest-title-line h3{margin:0;font-size:13px}.contest-main p{display:flex;gap:18px;color:var(--text-tertiary);font-size:9px}.contest-result{display:flex;flex-direction:column}.contest-result small{color:var(--text-tertiary);font-size:9px}.contest-result strong{font-size:16px}.contest-result em{font-size:9px;font-style:normal}.form-tip{display:block;margin-top:5px;color:var(--text-tertiary);font-size:9px}.password-notice{display:flex;gap:8px;padding:11px;margin-bottom:20px;border-radius:7px;background:var(--primary-soft);font-size:10px}@media(max-width:850px){.profile-content-grid{grid-template-columns:1fr}.profile-hero{padding:25px}.ranking-block{display:none}}@media(max-width:600px){.profile-hero{flex-direction:column;align-items:flex-start}.profile-avatar{width:64px;height:64px}.profile-meta{flex-direction:column}.recent-item>time,.row-action,.contest-source{display:none}.contest-item{flex-wrap:wrap;gap:12px}.contest-main{min-width:100%}.hero-side{align-self:stretch}.profile-actions{width:100%}}
</style>
