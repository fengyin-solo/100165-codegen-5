<template>
  <section class="page" data-module="tenant">
    <header class="page-head">
      <div>
        <h2>商业租户</h2>
        <p class="page-desc">
          维护租户合同（租户名称、铺位号、合同起止、月租金、保证金），按合同生成租金台账，
          导入账单逐行核销；铺位在租状态随合同生效与终止。
        </p>
      </div>
      <div class="page-actions">
        <button v-if="activeTab === 'contract'" class="btn primary" type="button" @click="openCreateContract">登记合同</button>
        <button v-if="activeTab === 'ledger'" class="btn primary" type="button" @click="openImport">导入账单核销</button>
        <button v-if="activeTab === 'ledger'" class="btn" type="button" @click="exportLedgers">另存租金台账清单</button>
        <button v-if="activeTab === 'ledger'" class="btn ghost" type="button" @click="downloadTemplate">下载账单模板</button>
      </div>
    </header>

    <div class="tab-row">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-item"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 租户合同 -->
    <div v-if="activeTab === 'contract'">
      <form class="filter-bar" @submit.prevent="loadContracts">
        <label class="filter-item">
          <span>关键字</span>
          <input v-model="contractKeyword" placeholder="按租户名称 / 铺位号 / 合同编号检索" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetContractFilter">重置条件</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in contractColumns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in contracts" :key="String(row.id)">
            <td v-for="column in contractColumns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="openEditContract(row)">编辑</button>
              <button class="link" type="button" @click="switchToLedger(String(row.铺位号))">查看台账</button>
              <button class="link" type="button" @click="terminateContract(row)">终止合同</button>
            </td>
          </tr>
          <tr v-if="!contracts.length">
            <td :colspan="contractColumns.length + 1" class="empty-state">暂无租户合同，可先登记合同</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ contracts.length }} 份合同（铺位在租状态随合同起止与终止情况实时推导）</span>
        <span v-if="message" class="ok-text">{{ message }}</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </div>

    <!-- 租金台账 -->
    <div v-if="activeTab === 'ledger'">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">账期总数</span>
          <strong class="stat-value">{{ summary.总期数 }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">应收合计</span>
          <strong class="stat-value">¥{{ formatMoney(summary.应收合计) }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">已核销合计</span>
          <strong class="stat-value">¥{{ formatMoney(summary.已核销合计) }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">待核销合计</span>
          <strong class="stat-value">¥{{ formatMoney(summary.待核销合计) }}</strong>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="loadLedgers">
        <label class="filter-item">
          <span>铺位号</span>
          <input v-model="ledgerFilters.booth" placeholder="按铺位号检索" />
        </label>
        <label class="filter-item">
          <span>账期</span>
          <input v-model="ledgerFilters.period" placeholder="YYYY-MM" />
        </label>
        <label class="filter-item">
          <span>核销状态</span>
          <input v-model="ledgerFilters.status" placeholder="已核销 / 待核销" />
        </label>
        <label class="filter-item">
          <span>关键字</span>
          <input v-model="ledgerFilters.keyword" placeholder="租户名称 / 合同编号" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetLedgerFilter">重置条件</button>
      </form>

      <div v-if="importResult" class="import-panel">
        <div class="import-head">
          <span>
            本次导入共 {{ importResult.总行数 }} 行：成功
            <b class="ok-text">{{ importResult.成功行数 }}</b> 行，跳过
            <b class="error-text">{{ importResult.跳过行数 }}</b> 行，核销金额
            <b>¥{{ formatMoney(importResult.核销金额) }}</b>
          </span>
          <button class="link" type="button" @click="importResult = null">收起明细</button>
        </div>
        <table class="import-table">
          <thead>
            <tr><th>文件行号</th><th>铺位号</th><th>账期</th><th>账单编号</th><th>金额</th><th>结果</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="detail in importResult.明细" :key="detail.行号">
              <td>{{ detail.行号 }}</td>
              <td>{{ detail.铺位号 || '—' }}</td>
              <td>{{ detail.账期 || '—' }}</td>
              <td>{{ detail.账单编号 || '—' }}</td>
              <td>{{ detail.金额 || '—' }}</td>
              <td>
                <span class="tag" :class="detail.ok ? 'ok' : 'bad'">{{ detail.ok ? '入账' : '跳过' }}</span>
              </td>
              <td :class="detail.ok ? 'ok-text' : 'error-text'">{{ detail.原因 }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledgers" :key="String(row.id)">
            <td v-for="column in ledgerColumns" :key="column">
              <span v-if="column === '应收金额' || column === '实收金额'">¥{{ formatMoney(row[column]) }}</span>
              <span v-else-if="column === '核销状态'" class="tag" :class="row[column] === '已核销' ? 'paid' : 'due'">{{ row[column] }}</span>
              <template v-else>{{ row[column] === '' || row[column] == null ? '—' : row[column] }}</template>
            </td>
          </tr>
          <tr v-if="!ledgers.length">
            <td :colspan="ledgerColumns.length" class="empty-state">当前筛选条件下没有租金台账</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ ledgerTotal }} 期台账（合计按筛选后的全量数据计算，与另存清单一致）</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </div>

    <!-- 铺位在租状态 -->
    <div v-if="activeTab === 'booth'">
      <form class="filter-bar" @submit.prevent="loadBooths">
        <label class="filter-item">
          <span>铺位号</span>
          <input v-model="boothFilters.booth" placeholder="按铺位号检索" />
        </label>
        <label class="filter-item">
          <span>在租状态</span>
          <input v-model="boothFilters.status" placeholder="在租 / 未到期 / 已到期 / 已终止" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetBoothFilter">重置条件</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in boothColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in booths" :key="String(row.铺位号)">
            <td v-for="column in boothColumns" :key="column">
              <span v-if="column === '月租金' || column === '保证金'">¥{{ formatMoney(row[column]) }}</span>
              <span v-else-if="column === '在租状态'" class="tag" :class="row[column] === '在租' ? 'paid' : 'due'">{{ row[column] }}</span>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
          </tr>
          <tr v-if="!booths.length">
            <td :colspan="boothColumns.length" class="empty-state">暂无铺位信息</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ booths.length }} 个铺位（状态完全跟随租户合同）</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </div>

    <!-- 合同登记 / 编辑弹窗 -->
    <div v-if="contractFormOpen" class="modal-mask" @click.self="contractFormOpen = false">
      <div class="modal">
        <h3 class="modal-title">{{ editingContract ? '编辑租户合同' : '登记租户合同' }}</h3>
        <form @submit.prevent="saveContract">
          <div class="form-grid">
            <label class="form-item">
              <span>租户名称 *</span>
              <input v-model="contractForm.租户名称" placeholder="如：云岚咖啡" />
            </label>
            <label class="form-item">
              <span>铺位号 *</span>
              <input v-model="contractForm.铺位号" placeholder="如：B1-101" />
            </label>
            <label class="form-item">
              <span>合同开始 *</span>
              <input v-model="contractForm.合同开始" type="date" />
            </label>
            <label class="form-item">
              <span>合同截止 *</span>
              <input v-model="contractForm.合同截止" type="date" />
            </label>
            <label class="form-item">
              <span>月租金（元/月）*</span>
              <input v-model="contractForm.月租金" placeholder="如：12000" />
            </label>
            <label class="form-item">
              <span>保证金（元）*</span>
              <input v-model="contractForm.保证金" placeholder="如：24000" />
            </label>
          </div>
          <p v-if="formError" class="error-text" style="margin: 10px 0 0">{{ formError }}</p>
          <div class="modal-foot">
            <button class="btn ghost" type="button" @click="contractFormOpen = false">取消</button>
            <button class="btn primary" type="submit">保存</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 账单导入弹窗 -->
    <div v-if="importOpen" class="modal-mask" @click.self="importOpen = false">
      <div class="modal">
        <h3 class="modal-title">导入账单核销租金台账</h3>
        <p class="hint-text">
          CSV 须包含列：铺位号、账期、账单编号、金额（表头支持别名）。
          缺列整文件拒绝；缺列内容、金额与月租金对不上、同一账期重复时只跳过该行并逐行提示，其余正常入账。
        </p>
        <input ref="fileInput" type="file" accept=".csv,text/csv" @change="uploadBills" />
        <p v-if="importError" class="error-text" style="margin: 10px 0 0">{{ importError }}</p>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="importOpen = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

type LedgerSummary = {
  总期数: number
  已核销期数: number
  待核销期数: number
  应收合计: number
  已核销合计: number
  待核销合计: number
}

type ImportDetail = {
  行号: number
  ok: boolean
  铺位号: string
  账期: string
  账单编号: string
  金额: string | number
  原因: string
}

type ImportResult = {
  总行数: number
  成功行数: number
  跳过行数: number
  核销金额: number
  明细: ImportDetail[]
}

const ENDPOINT = '/api/tenant'

const tabs = [
  { key: 'contract', label: '租户合同' },
  { key: 'ledger', label: '租金台账' },
  { key: 'booth', label: '铺位在租状态' },
] as const
type TabKey = (typeof tabs)[number]['key']

const activeTab = ref<TabKey>('contract')

const contractColumns = ['合同编号', '租户名称', '铺位号', '合同开始', '合同截止', '月租金', '保证金', '在租状态']
const ledgerColumns = ['合同编号', '租户名称', '铺位号', '账期', '应收金额', '实收金额', '核销状态', '账单编号', '核销日期']
const boothColumns = ['铺位号', '在租状态', '租户名称', '合同编号', '合同开始', '合同截止', '月租金', '保证金']

const emptySummary = (): LedgerSummary => ({
  总期数: 0,
  已核销期数: 0,
  待核销期数: 0,
  应收合计: 0,
  已核销合计: 0,
  待核销合计: 0,
})

const contracts = ref<Row[]>([])
const ledgers = ref<Row[]>([])
const booths = ref<Row[]>([])
const ledgerTotal = ref(0)
const summary = ref<LedgerSummary>(emptySummary())

const contractKeyword = ref('')
const ledgerFilters = reactive({ booth: '', period: '', status: '', keyword: '' })
const boothFilters = reactive({ booth: '', status: '' })

const errorMessage = ref('')
const message = ref('')
const formError = ref('')
const importError = ref('')
const importResult = ref<ImportResult | null>(null)

const contractFormOpen = ref(false)
const importOpen = ref(false)
const editingContract = ref<Row | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const contractForm = reactive({
  租户名称: '',
  铺位号: '',
  合同开始: '',
  合同截止: '',
  月租金: '',
  保证金: '',
})

function formatMoney(value: unknown): string {
  const amount = typeof value === 'number' ? value : Number(value ?? 0)
  return Number.isFinite(amount) ? amount.toFixed(2) : '0.00'
}

async function loadContracts() {
  errorMessage.value = ''
  message.value = ''
  const query = new URLSearchParams()
  if (contractKeyword.value.trim()) query.set('keyword', contractKeyword.value.trim())
  const response = await request(`${ENDPOINT}/contracts?${query.toString()}`)
  if (!response.ok) {
    errorMessage.value = '租户合同列表读取失败'
    return
  }
  const payload = await response.json()
  contracts.value = (payload.items ?? []) as Row[]
}

function resetContractFilter() {
  contractKeyword.value = ''
  void loadContracts()
}

async function loadLedgers() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (ledgerFilters.booth.trim()) query.set('booth', ledgerFilters.booth.trim())
  if (ledgerFilters.period.trim()) query.set('period', ledgerFilters.period.trim())
  if (ledgerFilters.status.trim()) query.set('status', ledgerFilters.status.trim())
  if (ledgerFilters.keyword.trim()) query.set('keyword', ledgerFilters.keyword.trim())
  const response = await request(`${ENDPOINT}/ledgers?${query.toString()}`)
  if (!response.ok) {
    errorMessage.value = '租金台账读取失败'
    return
  }
  const payload = await response.json()
  ledgers.value = (payload.items ?? []) as Row[]
  ledgerTotal.value = payload.total ?? ledgers.value.length
  summary.value = (payload.summary ?? emptySummary()) as LedgerSummary
}

function resetLedgerFilter() {
  ledgerFilters.booth = ''
  ledgerFilters.period = ''
  ledgerFilters.status = ''
  ledgerFilters.keyword = ''
  void loadLedgers()
}

async function loadBooths() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (boothFilters.booth.trim()) query.set('booth', boothFilters.booth.trim())
  if (boothFilters.status.trim()) query.set('status', boothFilters.status.trim())
  const response = await request(`${ENDPOINT}/booths?${query.toString()}`)
  if (!response.ok) {
    errorMessage.value = '铺位状态读取失败'
    return
  }
  const payload = await response.json()
  booths.value = (payload.items ?? []) as Row[]
}

function resetBoothFilter() {
  boothFilters.booth = ''
  boothFilters.status = ''
  void loadBooths()
}

function switchTab(key: TabKey) {
  activeTab.value = key
  if (key === 'contract') void loadContracts()
  if (key === 'ledger') void loadLedgers()
  if (key === 'booth') void loadBooths()
}

function switchToLedger(booth: string) {
  ledgerFilters.booth = booth
  activeTab.value = 'ledger'
  void loadLedgers()
}

function openCreateContract() {
  editingContract.value = null
  formError.value = ''
  Object.assign(contractForm, {
    租户名称: '',
    铺位号: '',
    合同开始: '',
    合同截止: '',
    月租金: '',
    保证金: '',
  })
  contractFormOpen.value = true
}

function openEditContract(row: Row) {
  editingContract.value = row
  formError.value = ''
  Object.assign(contractForm, {
    租户名称: String(row.租户名称 ?? ''),
    铺位号: String(row.铺位号 ?? ''),
    合同开始: String(row.合同开始 ?? ''),
    合同截止: String(row.合同截止 ?? ''),
    月租金: String(row.月租金 ?? ''),
    保证金: String(row.保证金 ?? ''),
  })
  contractFormOpen.value = true
}

async function saveContract() {
  formError.value = ''
  const editing = editingContract.value
  const url = editing ? `${ENDPOINT}/contracts/${editing.id}` : `${ENDPOINT}/contracts`
  const method = editing ? 'PUT' : 'POST'
  const response = await request(url, {
    method,
    body: JSON.stringify({ values: { ...contractForm } }),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok || !payload?.ok) {
    formError.value = payload?.detail ?? payload?.message ?? '合同保存失败'
    return
  }
  message.value = payload.message as string
  contractFormOpen.value = false
  await loadContracts()
}

async function terminateContract(row: Row) {
  errorMessage.value = ''
  message.value = ''
  const response = await request(`${ENDPOINT}/contracts/${row.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action: '终止合同' }),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok || !payload?.ok) {
    errorMessage.value = payload?.detail ?? payload?.message ?? '合同终止失败'
    return
  }
  message.value = payload.message as string
  await loadContracts()
}

function openImport() {
  importError.value = ''
  importResult.value = null
  importOpen.value = true
}

async function uploadBills(event: Event) {
  importError.value = ''
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  // 走 FormData 时不能手写 Content-Type，否则会把 multipart 边界覆盖掉。
  const response = await fetch(`${ENDPOINT}/ledgers/import`, { method: 'POST', body: form }).catch(
    (error: unknown) => {
      const detail = error instanceof Error ? error.message : '请求未送达'
      throw new Error(`接口请求失败：${detail}`)
    },
  )
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    importError.value = payload?.detail ?? '账单导入失败'
    return
  }
  importResult.value = payload as ImportResult
  importOpen.value = false
  await loadLedgers()
  await loadContracts()
}

function exportLedgers() {
  const query = new URLSearchParams()
  if (ledgerFilters.booth.trim()) query.set('booth', ledgerFilters.booth.trim())
  if (ledgerFilters.period.trim()) query.set('period', ledgerFilters.period.trim())
  if (ledgerFilters.status.trim()) query.set('status', ledgerFilters.status.trim())
  if (ledgerFilters.keyword.trim()) query.set('keyword', ledgerFilters.keyword.trim())
  window.open(`${ENDPOINT}/ledgers/export?${query.toString()}`, '_blank')
}

function downloadTemplate() {
  const csv = '﻿铺位号,账期,账单编号,金额\nB1-101,2026-09,BILL-示例-0001,12000\n'
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = '租金账单导入模板.csv'
  anchor.click()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  void loadContracts()
})
</script>
