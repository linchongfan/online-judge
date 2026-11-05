<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Back, Check, Lock, Message, Right, User } from '@element-plus/icons-vue'
import AppLogo from '../components/AppLogo.vue'
import { requestPasswordResetCode, resetPassword } from '../api/auth'
import { ApiError } from '../api/client'
import { login, register } from '../stores/session'
import type { UserRole } from '../types'

type AuthMode = 'login' | 'register' | 'forgot'

const route = useRoute()
const router = useRouter()
const mode = computed<AuthMode>(() => {
  const value = route.meta.mode
  return value === 'register' || value === 'forgot' ? value : 'login'
})

const loginFormRef = ref<FormInstance>()
const registerFormRef = ref<FormInstance>()
const forgotFormRef = ref<FormInstance>()
const loading = ref(false)
const codeSending = ref(false)
const recovered = ref(false)
const countdown = ref(0)
let countdownTimer: ReturnType<typeof setInterval> | undefined

const loginForm = reactive({ account: '', password: '', remember: true })
const registerForm = reactive({ username: '', nickname: '', email: '', password: '', confirmPassword: '', agreement: false })
const forgotForm = reactive({ email: '', code: '', password: '', confirmPassword: '' })
const isDev = import.meta.env.DEV

const copy = computed(() => ({
  login: { eyebrow: '账号登录', title: '欢迎回来', description: '继续整理算法思路，让每一次提交都有新的收获。' },
  register: { eyebrow: '加入新保研', title: '创建你的账号', description: '从第一道 Accepted 开始，建立属于自己的练习节奏。' },
  forgot: { eyebrow: '账号找回', title: '找回密码', description: '验证注册邮箱后，即可为账号设置新密码。' },
}[mode.value]))

const authQuery = computed(() => {
  const query: Record<string, string> = {}
  if (typeof route.query.redirect === 'string') query.redirect = route.query.redirect
  return query
})

const passwordValidator = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  if (!value) return callback(new Error('请输入密码'))
  if (value.length < 8) return callback(new Error('密码至少需要 8 个字符'))
  if (value.length > 128) return callback(new Error('密码不能超过 128 个字符'))
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) return callback(new Error('密码需同时包含字母和数字'))
  callback()
}

const loginRules: FormRules = {
  account: [
    { required: true, message: '请输入用户名或邮箱', trigger: 'blur' },
    { min: 3, max: 255, message: '账号长度为 3–255 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { max: 128, message: '密码不能超过 128 个字符', trigger: 'blur' },
  ],
}

const registerRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_]{3,32}$/, message: '使用 3–32 位字母、数字或下划线', trigger: 'blur' },
  ],
  nickname: [
    { required: true, message: '请输入昵称', trigger: 'blur' },
    { min: 1, max: 50, message: '昵称长度为 1–50 个字符', trigger: 'blur' },
  ],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }, { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' }],
  password: [{ required: true, trigger: 'blur', validator: passwordValidator }],
  confirmPassword: [{
    required: true,
    trigger: 'blur',
    validator: (_rule, value, callback) => {
      if (!value) callback(new Error('请再次输入密码'))
      else if (value !== registerForm.password) callback(new Error('两次输入的密码不一致'))
      else callback()
    },
  }],
  agreement: [{
    validator: (_rule, value, callback) => value ? callback() : callback(new Error('请阅读并同意服务条款与隐私政策')),
    trigger: 'change',
  }],
}

const forgotRules: FormRules = {
  email: [{ required: true, message: '请输入注册邮箱', trigger: 'blur' }, { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' }],
  code: [{ required: true, message: '请输入验证码', trigger: 'blur' }, { pattern: /^\d{6}$/, message: '验证码为 6 位数字', trigger: 'blur' }],
  password: [{ required: true, trigger: 'blur', validator: passwordValidator }],
  confirmPassword: [{
    required: true,
    trigger: 'blur',
    validator: (_rule, value, callback) => {
      if (!value) callback(new Error('请再次输入新密码'))
      else if (value !== forgotForm.password) callback(new Error('两次输入的密码不一致'))
      else callback()
    },
  }],
}

function destinationFor(role: UserRole) {
  const redirect = route.query.redirect
  if (typeof redirect === 'string' && redirect.startsWith('/') && !redirect.startsWith('//')) return redirect
  return role === 'admin' ? '/admin/dashboard' : '/problems'
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

async function validate(form?: FormInstance) {
  if (!form) return false
  try {
    await form.validate()
    return true
  } catch {
    return false
  }
}

async function submitLogin() {
  if (loading.value || !await validate(loginFormRef.value)) return
  loading.value = true
  try {
    const profile = await login({
      account: loginForm.account.trim(),
      password: loginForm.password,
      remember: loginForm.remember,
    })
    ElMessage.success(profile.role === 'admin' ? '管理员身份验证成功' : '登录成功，欢迎回来')
    await router.replace(destinationFor(profile.role))
  } catch (error) {
    ElMessage.error(errorMessage(error, '登录失败，请稍后重试'))
  } finally {
    loading.value = false
  }
}

async function submitRegister() {
  if (loading.value || !await validate(registerFormRef.value)) return
  loading.value = true
  try {
    const profile = await register({
      username: registerForm.username.trim(),
      nickname: registerForm.nickname.trim(),
      email: registerForm.email.trim(),
      password: registerForm.password,
    })
    ElMessage.success('账号创建成功，已为你自动登录')
    await router.replace(destinationFor(profile.role))
  } catch (error) {
    ElMessage.error(errorMessage(error, '注册失败，请稍后重试'))
  } finally {
    loading.value = false
  }
}

function startCountdown() {
  if (countdownTimer) clearInterval(countdownTimer)
  countdown.value = 60
  countdownTimer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0 && countdownTimer) {
      clearInterval(countdownTimer)
      countdownTimer = undefined
    }
  }, 1000)
}

async function sendCode() {
  if (codeSending.value || countdown.value > 0 || !forgotFormRef.value) return
  try {
    await forgotFormRef.value.validateField('email')
  } catch {
    return
  }
  codeSending.value = true
  try {
    const response = await requestPasswordResetCode({ email: forgotForm.email.trim() })
    ElMessage.success(response.message || '验证码已发送，请查收邮件')
    startCountdown()
  } catch (error) {
    ElMessage.error(errorMessage(error, '验证码发送失败，请稍后重试'))
  } finally {
    codeSending.value = false
  }
}

async function submitForgot() {
  if (loading.value || !await validate(forgotFormRef.value)) return
  loading.value = true
  try {
    const response = await resetPassword({
      email: forgotForm.email.trim(),
      code: forgotForm.code,
      newPassword: forgotForm.password,
    })
    recovered.value = true
    forgotForm.password = ''
    forgotForm.confirmPassword = ''
    ElMessage.success(response.message || '密码已重置，请使用新密码登录')
  } catch (error) {
    ElMessage.error(errorMessage(error, '密码重置失败，请检查验证码后重试'))
  } finally {
    loading.value = false
  }
}

function submitCurrent() {
  if (mode.value === 'login') void submitLogin()
  else if (mode.value === 'register') void submitRegister()
  else void submitForgot()
}

function backToLogin() {
  loginForm.account = forgotForm.email
  void router.push({ path: '/login', query: authQuery.value })
}

watch(mode, async () => {
  recovered.value = false
  await nextTick()
  loginFormRef.value?.clearValidate()
  registerFormRef.value?.clearValidate()
  forgotFormRef.value?.clearValidate()
})

onBeforeUnmount(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})
</script>

<template>
  <main class="auth-page">
    <section class="brand-panel">
      <div class="brand-content">
        <AppLogo class="brand-logo" />
        <div class="brand-story">
          <div class="story-copy">
            <span class="brand-kicker"><i /> 算法练习与研途积累</span>
            <h1>保研更有方向，<br>上岸更有把握。</h1>
            <p>把复杂问题拆小，把解题思路讲清。<br>在新保研，用一次次练习打好计算机基础。</p>
            <div class="study-topics" aria-label="练习重点">
              <span>边界条件</span><span>复杂度分析</span><span>测试用例</span>
            </div>
          </div>
          <div class="owl-study" aria-label="新保研猫头鹰学习伙伴">
            <span class="owl-note">今天，也把一道题弄懂</span>
            <img src="/images/xinbaoyan-mark.png" alt="新保研猫头鹰" />
          </div>
        </div>
        <div class="code-window" aria-label="代码通过示例">
          <div class="window-bar">
            <span class="window-dots"><i /><i /><i /></span>
            <span class="mono">solution.cpp</span>
            <span class="window-state"><i /> 判题完成</span>
          </div>
          <pre class="mono"><span class="code-type">vector</span>&lt;<span class="code-type">int</span>&gt; result;
<span class="code-keyword">for</span> (<span class="code-type">int</span> i = <span class="code-number">0</span>; i &lt; n; ++i) {
  <span class="code-comment">// 先验证思路，再优化复杂度</span>
  result.push_back(nums[i]);
}</pre>
          <div class="judge-result">
            <span class="result-check"><el-icon><Check /></el-icon></span>
            <div><strong>Accepted</strong><span>所有测试用例均已通过</span></div>
            <span class="mono result-time">16 ms</span>
          </div>
        </div>
        <div class="study-rhythm" aria-label="算法练习节奏">
          <span><i>1</i>读题拆解</span><b /><span><i>2</i>编码验证</span><b /><span><i>3</i>复盘归类</span>
        </div>
      </div>
      <span class="brand-footer">新保研 · 把每一次提交，变成下一次进步的依据</span>
    </section>

    <section class="form-panel">
      <div class="mobile-brand"><AppLogo /></div>
      <div class="auth-card" :class="{ 'is-register': mode === 'register' }">
        <template v-if="!recovered">
          <div class="form-heading">
            <span class="eyebrow">{{ copy.eyebrow }}</span>
            <h2>{{ copy.title }}</h2>
            <p>{{ copy.description }}</p>
          </div>

          <el-form v-if="mode === 'login'" ref="loginFormRef" :model="loginForm" :rules="loginRules" label-position="top" size="large" @submit.prevent="submitCurrent">
            <el-form-item label="用户名或邮箱" prop="account">
              <el-input v-model.trim="loginForm.account" placeholder="请输入用户名或邮箱" autocomplete="username" :prefix-icon="User" />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input v-model="loginForm.password" type="password" placeholder="请输入密码" autocomplete="current-password" show-password :prefix-icon="Lock" />
            </el-form-item>
            <div class="form-options">
              <el-checkbox v-model="loginForm.remember">保持登录状态</el-checkbox>
              <router-link :to="{ path: '/forgot', query: authQuery }">忘记密码？</router-link>
            </div>
            <el-button class="submit-button" type="primary" native-type="submit" :loading="loading">登 录</el-button>
            <p class="mode-switch">还没有账号？<router-link :to="{ path: '/register', query: authQuery }">免费注册<el-icon><Right /></el-icon></router-link></p>
          </el-form>

          <el-form v-else-if="mode === 'register'" ref="registerFormRef" :model="registerForm" :rules="registerRules" label-position="top" size="large" @submit.prevent="submitCurrent">
            <div class="field-row">
              <el-form-item label="用户名" prop="username">
                <el-input v-model.trim="registerForm.username" placeholder="用于登录，3–20 位" autocomplete="username" />
              </el-form-item>
              <el-form-item label="昵称" prop="nickname">
                <el-input v-model.trim="registerForm.nickname" placeholder="在社区中展示的名字" autocomplete="nickname" />
              </el-form-item>
            </div>
            <el-form-item label="邮箱地址" prop="email">
              <el-input v-model.trim="registerForm.email" placeholder="name@example.com" autocomplete="email" :prefix-icon="Message" />
            </el-form-item>
            <div class="field-row">
              <el-form-item label="设置密码" prop="password">
                <el-input v-model="registerForm.password" type="password" placeholder="至少 8 位，含字母和数字" autocomplete="new-password" show-password />
              </el-form-item>
              <el-form-item label="确认密码" prop="confirmPassword">
                <el-input v-model="registerForm.confirmPassword" type="password" placeholder="再次输入密码" autocomplete="new-password" show-password />
              </el-form-item>
            </div>
            <el-form-item prop="agreement" class="agreement-item">
              <el-checkbox v-model="registerForm.agreement">我已阅读并同意服务条款与隐私政策</el-checkbox>
            </el-form-item>
            <el-button class="submit-button" type="primary" native-type="submit" :loading="loading">创建账号</el-button>
            <p class="mode-switch">已有账号？<router-link :to="{ path: '/login', query: authQuery }">直接登录<el-icon><Right /></el-icon></router-link></p>
          </el-form>

          <el-form v-else ref="forgotFormRef" :model="forgotForm" :rules="forgotRules" label-position="top" size="large" @submit.prevent="submitCurrent">
            <el-form-item label="注册邮箱" prop="email">
              <el-input v-model.trim="forgotForm.email" placeholder="请输入账号绑定的邮箱" autocomplete="email" :prefix-icon="Message" />
            </el-form-item>
            <el-form-item label="邮箱验证码" prop="code">
              <div class="code-field">
                <el-input v-model.trim="forgotForm.code" class="mono" placeholder="6 位数字验证码" maxlength="6" inputmode="numeric" />
                <el-button :disabled="countdown > 0" @click="sendCode">{{ countdown > 0 ? `${countdown}s 后重发` : '发送验证码' }}</el-button>
              </div>
              <span v-if="isDev" class="field-tip">开发环境验证码写入 data/mail_outbox/ 目录</span>
            </el-form-item>
            <el-form-item label="新密码" prop="password">
              <el-input v-model="forgotForm.password" type="password" placeholder="至少 8 位，含字母和数字" autocomplete="new-password" show-password :prefix-icon="Lock" />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirmPassword">
              <el-input v-model="forgotForm.confirmPassword" type="password" placeholder="再次输入新密码" autocomplete="new-password" show-password />
            </el-form-item>
            <el-button class="submit-button" type="primary" native-type="submit" :loading="loading">重置密码</el-button>
            <p class="mode-switch"><router-link :to="{ path: '/login', query: authQuery }"><el-icon><Back /></el-icon>返回登录</router-link></p>
          </el-form>
        </template>

        <div v-else class="recovery-success">
          <div class="success-mark"><el-icon><Check /></el-icon></div>
          <span class="eyebrow">账号已恢复</span>
          <h2>密码重置成功</h2>
          <p>你的账号密码已更新。<br>现在可以使用新密码继续登录新保研。</p>
          <el-button type="primary" size="large" @click="backToLogin">返回登录</el-button>
          <button type="button" class="back-home" @click="router.push('/problems')">先去看看题库</button>
        </div>
      </div>
      <footer class="form-footer"><span>© 2026 新保研</span><span>安全登录 · 隐私保护</span></footer>
    </section>
  </main>
</template>

<style scoped>
.auth-page { min-height: 100vh; display: grid; grid-template-columns: minmax(520px, 1.08fr) minmax(500px, .92fr); background: #fff; }
.brand-panel { position: relative; overflow: hidden; min-height: 100vh; padding: 36px clamp(36px, 4vw, 64px) 26px; color: var(--text); background: #edf4ff; border-right: 1px solid #dce8f8; display: flex; flex-direction: column; }
.brand-panel::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 6px; background: var(--primary); }
.brand-panel::after { content: ''; position: absolute; right: 0; top: 0; width: 96px; height: 8px; background: var(--accent); }
.brand-content { width: 100%; max-width: 640px; margin: auto; position: relative; z-index: 1; }
.brand-logo { display: inline-flex; }
.brand-logo :deep(.brand-mark) { width: 52px; height: 52px; border: 1px solid #dbe7f7; }
.brand-logo :deep(.brand-mark img) { width: 48px; height: 45px; }
.brand-logo :deep(.brand-type strong) { font-size: 25px; }
.brand-story { display: grid; grid-template-columns: minmax(0, 1fr) 176px; align-items: center; gap: 22px; margin-top: clamp(42px, 6vh, 68px); }
.brand-kicker { display: flex; align-items: center; gap: 9px; color: var(--primary); font-size: 12px; font-weight: 600; letter-spacing: .5px; }
.brand-kicker i { width: 22px; height: 3px; border-radius: 2px; background: var(--accent); }
.brand-story h1 { margin: 17px 0 16px; color: #103d87; font-size: clamp(34px, 3.15vw, 45px); line-height: 1.38; letter-spacing: -1.5px; font-weight: 700; }
.brand-story p { color: #526d8e; line-height: 1.9; font-size: 13px; margin: 0; }
.study-topics { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 20px; }
.study-topics span { padding: 5px 9px; border: 1px solid #ccdef5; border-radius: 5px; background: rgba(255,255,255,.65); color: #426589; font-size: 10px; }
.owl-study { position: relative; align-self: end; padding: 22px 10px 8px; border: 1px solid #d4e3f6; border-radius: 84px 84px 16px 16px; background: #fff; }
.owl-study img { display: block; width: 100%; height: auto; }
.owl-note { position: absolute; z-index: 1; top: 5px; left: -38px; padding: 8px 11px; border-left: 3px solid var(--accent); border-radius: 5px; background: #fff; box-shadow: 0 7px 20px rgba(34,76,135,.08); color: var(--text); font-size: 10px; white-space: nowrap; transform: rotate(-3deg); }
.code-window { margin-top: 34px; border-radius: 12px; border: 1px solid #cbdcf1; background: #fff; box-shadow: 0 18px 36px rgba(34,76,135,.08); overflow: hidden; }
.window-bar { height: 42px; padding: 0 16px; display: flex; align-items: center; gap: 15px; border-bottom: 1px solid #e4edf8; background: #f8fbff; color: var(--text-tertiary); font-size: 10px; }
.window-dots { display: flex; gap: 5px; }
.window-dots i { width: 6px; height: 6px; border-radius: 50%; background: #9eb5d1; }
.window-dots i:first-child { background: #df8d91; }
.window-dots i:nth-child(2) { background: var(--accent); }
.window-dots i:last-child { background: #55aa8e; }
.window-state { margin-left: auto; display: flex; align-items: center; gap: 5px; color: var(--text-secondary); }
.window-state i { width: 5px; height: 5px; border-radius: 50%; background: var(--success); }
.code-window pre { padding: 17px 23px; margin: 0; color: #29415f; font-size: 12px; line-height: 1.85; overflow-x: auto; }
.code-type { color: #1557d6; }.code-keyword { color: #0c409f; font-weight: 600; }.code-number { color: #c87620; }.code-comment { color: #8296ad; }
.judge-result { display: flex; align-items: center; gap: 11px; padding: 12px 18px; background: #f0f9f5; border-top: 1px solid #dcefe6; }
.result-check { width: 29px; height: 29px; display: grid; place-items: center; border-radius: 50%; color: var(--success); background: #dcf1e7; }
.judge-result div { display: flex; flex-direction: column; gap: 2px; }
.judge-result strong { color: var(--success); font-size: 12px; }.judge-result div span { color: #6c897d; font-size: 9px; }.result-time { margin-left: auto; color: var(--text-tertiary); font-size: 10px; }
.study-rhythm { display: flex; align-items: center; justify-content: center; gap: 11px; margin-top: 24px; color: var(--text-secondary); font-size: 10px; }
.study-rhythm span { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.study-rhythm i { width: 19px; height: 19px; display: grid; place-items: center; border-radius: 50%; background: #fff; border: 1px solid #ccdef3; color: var(--primary); font-size: 9px; font-style: normal; font-weight: 600; }
.study-rhythm b { width: 24px; height: 1px; background: #bfd3ed; }
.brand-footer { position: relative; z-index: 1; color: #7890ac; font-size: 10px; text-align: center; margin-top: 28px; }
.form-panel { min-height: 100vh; padding: 40px 50px 22px; display: flex; flex-direction: column; justify-content: center; align-items: center; background: #fff; }
.auth-card { width: 100%; max-width: 410px; margin: auto; }
.auth-card.is-register { max-width: 510px; }
.mobile-brand { display: none; }
.form-heading { margin-bottom: 27px; }
.form-heading .eyebrow { margin-bottom: 10px; }
.form-heading h2, .recovery-success h2 { margin: 0; color: var(--text-strong); font-size: 29px; letter-spacing: -.8px; }
.form-heading p { color: var(--text-secondary); margin: 10px 0 0; line-height: 1.7; font-size: 13px; }
.auth-card :deep(.el-form-item) { margin-bottom: 19px; }
.auth-card :deep(.el-form-item__label) { color: var(--text); font-size: 12px; font-weight: 500; padding-bottom: 7px !important; }
.auth-card :deep(.el-input__wrapper) { padding: 4px 13px; }
.form-options { margin: -2px 0 22px; display: flex; align-items: center; justify-content: space-between; }
.form-options :deep(.el-checkbox__label) { font-size: 12px; color: var(--text-secondary); }
.form-options a { color: var(--primary); text-decoration: none; font-size: 12px; }
.submit-button { width: 100%; height: 43px; font-size: 14px; letter-spacing: 2px; box-shadow: 0 7px 18px rgba(21,87,214,.14); }
.mode-switch { margin: 23px 0 0; display: flex; justify-content: center; align-items: center; gap: 5px; color: var(--text-tertiary); font-size: 12px; }
.mode-switch a { color: var(--primary); text-decoration: none; display: inline-flex; align-items: center; gap: 3px; font-weight: 500; }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.agreement-item { margin-top: -3px; }
.agreement-item :deep(.el-checkbox__label) { font-size: 11px; color: var(--text-secondary); }
.agreement-item span { color: var(--primary); }
.code-field { display: flex; width: 100%; gap: 10px; }
.code-field .el-button { height: 40px; flex: none; }
.field-tip { display: block; color: var(--text-tertiary); font-size: 10px; line-height: 1.5; margin-top: 5px; }
.form-footer { width: 100%; display: flex; justify-content: space-between; color: var(--text-tertiary); font-size: 10px; margin-top: 30px; }
.recovery-success { text-align: center; padding: 30px 0; }
.success-mark { width: 68px; height: 68px; display: grid; place-items: center; margin: 0 auto 25px; border-radius: 20px; background: #eaf7f1; color: var(--success); font-size: 30px; box-shadow: 0 0 0 9px #f5fbf8; }
.recovery-success .eyebrow { margin-bottom: 10px; }
.recovery-success p { color: var(--text-secondary); line-height: 1.8; margin: 15px 0 27px; }
.recovery-success .el-button { width: 100%; }
.back-home { border: 0; background: transparent; color: var(--text-tertiary); font-size: 12px; cursor: pointer; margin-top: 20px; }
.back-home:hover { color: var(--primary); }
@media (max-width: 1100px) {
  .auth-page { grid-template-columns: minmax(430px, .9fr) minmax(500px, 1.1fr); }
  .brand-panel { padding-left: 34px; padding-right: 34px; }
  .brand-story { grid-template-columns: minmax(0, 1fr) 140px; gap: 16px; }
  .brand-story h1 { font-size: 34px; }
  .brand-story p { font-size: 12px; }
  .owl-note { left: -25px; font-size: 9px; }
  .study-topics { gap: 5px; }.study-topics span { padding: 4px 7px; font-size: 9px; }
  .form-panel { padding-left: 40px; padding-right: 40px; }
}
@media (max-width: 900px) {
  .auth-page { display: block; background: #fff; }
  .brand-panel { display: none; }
  .form-panel { padding: 28px 24px 20px; min-height: 100vh; justify-content: flex-start; }
  .mobile-brand { display: block; width: 100%; max-width: 510px; margin: 0 auto 48px; }
  .auth-card { margin: 0 auto; }
  .form-footer { max-width: 510px; margin-top: auto; padding-top: 42px; }
}
@media (max-width: 540px) {
  .form-panel { padding: 22px 18px 18px; }
  .mobile-brand { margin-bottom: 38px; }
  .form-heading h2 { font-size: 26px; }
  .field-row { grid-template-columns: 1fr; gap: 0; }
  .form-footer { padding-top: 35px; }
}
</style>
