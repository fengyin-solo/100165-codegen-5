<template>
  <section class="page" data-module="tenant">
    <header class="page-head">
      <div>
        <h2>商业租户管理</h2>
        <p class="page-desc">维护租户合同（铺位、起止、月租、保证金），按合同生成租金台账，导入账单逐行核销；铺位在租状态跟着合同走，重开页面仍然在。</p>
      </div>
    </header>

    <div class="tab-bar">
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
    <div v-show="activeTab === 'contract'">
      <div class="page-actions" style="margin: 8px 0 12px">
        <button class="btn primary" type="button" @click="openContractForm">新增租户合同</button>
        <button class="btn" type="button" @click="generateAll">按全部合同生成台账</button>
      </div>
      <form class="filter-bar" @submit.prevent="loadContracts">
        <label class="filter-item">
          <span>租户 / 铺位 / 合同编号</span>
          <input v-model="contractFilter.keyword" placeholder="按关键字检索" />
        </label>
        <label class="filter-item">
          <span>合同状态</span>
          <select v-model="contractFilter.status">
            <option value="">全部</option>
            <option v-for="s in contractStatuses" :key="s" :value="s">{{ s }}</option>
          </select>
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
            <td>{{ row['合同编号'] }}</td>
            <td>{{ row['租户名称'] }}</td>
            <td>{{ row['铺位号'] }}</td>
            <td>{{ row['合同开始'] }}</td>
            <td>{{ row['合同结束'] }}</td>
            <td>{{ formatMoney(row['月租金']) }}</td>
            <td>{{ formatMoney(row['保证金']) }}</td>
            <td>{{ row.status }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="generateForContract(row)">生成台账</button>
              <button
                v-if="row.status === '履行中'"
                class="link danger"
                type="button"
                @click="terminateContract(row)"
              >
                终止合同
              </button>
            </td>
          </tr>
          <tr v-if="!contracts.length">
            <td :colspan="contractColumns.length + 1" class="empty-state">暂无租户合同，可先新增一份</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ contractTotal }} 份租户合同</span>
        <span v-if="contractMessage" class="error-text">{{ contractMessage }}</span>
        <span v-else-if="contractNotice" class="ok-text">{{ contractNotice }}</span>
      </footer>
    </div>

    <!-- 租金台账 -->
    <div v-show="activeTab === 'ledger'">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">台账笔数</span>
          <strong class="stat-value">{{ summary.count }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">应收合计（元）</span>
          <strong class="stat-value">{{ formatMoney(summary.due_total) }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">已核销合计（元）</span>
          <strong class="stat-value">{{ formatMoney(summary.paid_total) }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">未核销合计（元）</span>
          <strong class="stat-value">{{ formatMoney(summary.unpaid_total) }}</strong>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="reloadLedger">
        <label class="filter-item">
          <span>租户 / 铺位 / 账单编号</span>
          <input v-model="ledgerFilter.keyword" placeholder="按关键字检索" />
        </label>
        <label class="filter-item">
          <span>核销状态</span>
          <select v-model="ledgerFilter.status">
            <option value="">全部</option>
            <option v-for="s in ledgerStatuses" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>铺位号</span>
          <input v-model="ledgerFilter.booth" placeholder="如 B1-08" />
        </label>
        <label class="filter-item">
          <span>账期</span>
          <input v-model="ledgerFilter.period" placeholder="YYYY-MM，如 2026-09" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetLedgerFilter">重置条件</button>
      </form>

      <div class="toolbar">
        <label class="btn primary file-btn">
          导入账单核销（CSV）
          <input ref="billInput" type="file" accept=".csv,text/csv" @change="onFilePicked" hidden />
        </label>
        <button class="btn" type="button" @click="exportLedger('csv')">另存清单 CSV</button>
        <button class="btn" type="button" @click="exportLedger('json')">另存清单 JSON</button>
        <a class="btn ghost" href="/api/tenant/ledger/import-template">下载账单模板</a>
        <span v-if="importing" class="hint">正在导入…</span>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledgerRows" :key="String(row.id)">
            <td>{{ row['合同编号'] }}</td>
            <td>{{ row['租户名称'] }}</td>
            <td>{{ row['铺位号'] }}</td>
            <td>{{ row['账期'] }}</td>
            <td>{{ formatMoney(row['应收金额']) }}</td>
            <td>{{ row['实收金额'] == null ? '—' : formatMoney(row['实收金额']) }}</td>
            <td>{{ row['账单编号'] || '—' }}</td>
            <td>{{ row['核销日期'] || '—' }}</td>
            <td>
              <span :class="row.status === '已核销' ? 'tag ok' : 'tag pending'">{{ row.status }}</span>
            </td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td :colspan="ledgerColumns.length" class="empty-state">暂无台账数据，请先在「租户合同」里按合同生成</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ ledgerTotal }} 条台账（当前查询条件，清单合计与上方卡片一致）</span>
        <span v-if="ledgerMessage" class="error-text">{{ ledgerMessage }}</span>
      </footer>

      <div v-if="importResult" class="import-panel">
        <h4>
          本次导入「{{ importResult.file_name }}」：共 {{ importResult.total }} 行，
          <span class="ok-text">入账 {{ importResult.imported }} 行</span>，
          <span class="error-text">跳过 {{ importResult.skipped }} 行</span>
        </h4>
        <ul class="import-lines">
          <li v-for="line in importResult.results" :key="line.line" :class="{ skip: !line.ok }">
            <span class="line-no">第 {{ line.line }} 行</span>
            <span :class="line.ok ? 'ok-text' : 'error-text'">{{ line.ok ? '入账' : '跳过' }}</span>
            <span>{{ line.message }}</span>
          </li>
        </ul>
      </div>
    </div>

    <!-- 铺位状态 -->
    <div v-show="activeTab === 'booth'">
      <form class="filter-bar" style="margin-top: 12px" @submit.prevent="loadBooths">
        <label class="filter-item">
          <span>铺位号 / 租户名称</span>
          <input v-model="boothFilter.keyword" placeholder="按关键字检索" />
        </label>
        <label class="filter-item">
          <span>在租状态</span>
          <select v-model="boothFilter.status">
            <option value="">全部</option>
            <option value="在租">在租</option>
            <option value="空闲">空闲</option>
          </select>
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
          <tr v-for="row in booths" :key="row['铺位号']">
            <td>{{ row['铺位号'] }}</td>
            <td>
              <span :class="row['在租状态'] === '在租' ? 'tag ok' : 'tag idle'">{{ row['在租状态'] }}</span>
            </td>
            <td>{{ row['租户名称'] || '—' }}</td>
            <td>{{ row['合同编号'] }}</td>
            <td>{{ row['合同开始'] }}</td>
            <td>{{ row['合同结束'] }}</td>
            <td>{{ formatMoney(row['月租金']) }}</td>
          </tr>
          <tr v-if="!booths.length">
            <td :colspan="boothColumns.length" class="empty-state">暂无铺位，登记租户合同后自动出现</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ booths.length }} 个铺位（状态由租户合同自动推导，其它模块查询方式不变）</span>
      </footer>
    </div>

    <!-- 新增合同弹窗 -->
    <div v-if="showContractModal" class="modal-mask" @click.self="showContractModal = false">
      <div class="modal">
        <h3>新增租户合同</h3>
        <div class="form-grid">
          <label v-for="field in contractFormFields" :key="field.key" class="form-item">
            <span>{{ field.label }}{{ field.required ? ' *' : '' }}</span>
            <input
              v-model="contractForm[field.key]"
              :type="field.type || 'text'"
              :placeholder="field.placeholder"
            />
          </label>
        </div>
        <p class="form-tip">合同登记保存后立即生效，铺位自动变为在租，页面重开仍然在。</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="showContractModal = false">取消</button>
          <button class="btn primary" type="button" :disabled="savingContract" @click="submitContract">
            {{ savingContract ? '保存中…' : '保存合同' }}
          </button>
        </div>
        <p v-if="contractFormError" class="error-text">{{ contractFormError }}</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type LedgerRow = Row
type BoothRow = Record<string, string | number>

interface ImportLine {
  line: number
  ok: boolean
  message: string
  raw: Record<string, string>
}
interface ImportResult {
  file_name: string
  total: number
  imported: number
  skipped: number
  missing_columns: string[]
  results: ImportLine[]
}
interface Summary {
  count: number
  due_total: number
  paid_total: number
  unpaid_total: number
}

const tabs = [
  { key: 'contract', label: '租户合同' },
  { key: 'ledger', label: '租金台账' },
  { key: 'booth', label: '铺位在租状态' },
] as const

const activeTab = ref<(typeof tabs)[number]['key']>('contract')

const contractColumns = ['合同编号', '租户名称', '铺位号', '合同开始', '合同结束', '月租金', '保证金', '合同状态']
const ledgerColumns = ['合同编号', '租户名称', '铺位号', '账期', '应收金额', '实收金额', '账单编号', '核销日期', '核销状态']
const boothColumns = ['铺位号', '在租状态', '当前租户', '合同编号', '合同开始', '合同结束', '月租金']
const contractStatuses = ['履行中', '已到期', '已终止']
const ledgerStatuses = ['待核销', '已核销']

// --------------------------------------------------------------- 合同
const contracts = ref<Row[]>([])
const contractTotal = ref(0)
const contractFilter = reactive({ keyword: '', status: '' })
const contractMessage = ref('')
const contractNotice = ref('')

const showContractModal = ref(false)
const savingContract = ref(false)
const contractFormError = ref('')
const contractFormFields = [
  { key: '合同编号', label: '合同编号', required: false, placeholder: '留空自动生成，如 HT-2026-005' },
  { key: '租户名称', label: '租户名称', required: true },
  { key: '铺位号', label: '铺位号', required: true, placeholder: '如 B1-08' },
  { key: '合同开始', label: '合同开始', required: true, type: 'date' },
  { key: '合同结束', label: '合同结束', required: true, type: 'date' },
  { key: '月租金', label: '月租金（元）', required: true, type: 'number', placeholder: '如 12000' },
  { key: '保证金', label: '保证金（元）', required: true, type: 'number', placeholder: '如 24000' },
]
const emptyContractForm = (): Record<string, string> => ({
  合同编号: '', 租户名称: '', 铺位号: '', 合同开始: '', 合同结束: '', 月租金: '', 保证金: '',
})
const contractForm = reactive<Record<string, string>>(emptyContractForm())

function openContractForm() {
  Object.assign(contractForm, emptyContractForm())
  contractFormError.value = ''
  showContractModal.value = true
}

async function submitContract() {
  contractFormError.value = ''
  savingContract.value = true
  try {
    const response = await request('/api/tenant/contracts', {
      method: 'POST',
      body: JSON.stringify({ values: { ...contractForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      contractFormError.value = payload.message || '合同登记失败'
      return
    }
    showContractModal.value = false
    contractNotice.value = payload.message
    await Promise.all([loadContracts(), loadBooths()])
  } catch (error) {
    contractFormError.value = error instanceof Error ? error.message : '合同登记失败'
  } finally {
    savingContract.value = false
  }
}

async function terminateContract(row: Row) {
  contractNotice.value = ''
  contractMessage.value = ''
  try {
    const response = await request(`/api/tenant/contracts/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: '终止合同' } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      contractMessage.value = payload.message || '合同终止失败'
      return
    }
    contractNotice.value = payload.message
    await Promise.all([loadContracts(), loadBooths()])
  } catch (error) {
    contractMessage.value = error instanceof Error ? error.message : '合同终止失败'
  }
}

async function generateForContract(row: Row) {
  await runGenerate({ contract_id: String(row.id) }, `已按合同 ${row['合同编号']} 生成台账`)
}

async function generateAll() {
  await runGenerate({}, '已按全部合同补齐台账，已有账期自动跳过')
}

async function runGenerate(values: Record<string, string | number>, okPrefix: string) {
  contractMessage.value = ''
  contractNotice.value = ''
  try {
    const response = await request('/api/tenant/ledger/generate', {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      contractMessage.value = payload.message || '台账生成失败'
      return
    }
    contractNotice.value = `${okPrefix}：${payload.message}`
    if (activeTab.value === 'ledger') {
      await reloadLedger()
    }
  } catch (error) {
    contractMessage.value = error instanceof Error ? error.message : '台账生成失败'
  }
}

function resetContractFilter() {
  contractFilter.keyword = ''
  contractFilter.status = ''
  void loadContracts()
}

async function loadContracts() {
  contractMessage.value = ''
  const query = new URLSearchParams()
  if (contractFilter.keyword) query.set('keyword', contractFilter.keyword)
  if (contractFilter.status) query.set('status', contractFilter.status)
  try {
    const response = await request(`/api/tenant/contracts?${query.toString()}`)
    if (!response.ok) throw new Error('租户合同列表读取失败')
    const payload = await response.json()
    contracts.value = payload.items ?? []
    contractTotal.value = payload.total ?? contracts.value.length
  } catch (error) {
    contractMessage.value = error instanceof Error ? error.message : '租户合同列表读取失败'
  }
}

// --------------------------------------------------------------- 台账
const ledgerRows = ref<LedgerRow[]>([])
const ledgerTotal = ref(0)
const ledgerMessage = ref('')
const ledgerFilter = reactive({ keyword: '', status: '', booth: '', period: '' })
const summary = ref<Summary>({ count: 0, due_total: 0, paid_total: 0, unpaid_total: 0 })

const billInput = ref<HTMLInputElement | null>(null)
const importing = ref(false)
const importResult = ref<ImportResult | null>(null)

function ledgerQueryString(): string {
  const query = new URLSearchParams()
  if (ledgerFilter.keyword) query.set('keyword', ledgerFilter.keyword)
  if (ledgerFilter.status) query.set('status', ledgerFilter.status)
  if (ledgerFilter.booth) query.set('booth', ledgerFilter.booth)
  if (ledgerFilter.period) query.set('period', ledgerFilter.period)
  return query.toString()
}

function resetLedgerFilter() {
  ledgerFilter.keyword = ''
  ledgerFilter.status = ''
  ledgerFilter.booth = ''
  ledgerFilter.period = ''
  void reloadLedger()
}

async function reloadLedger() {
  ledgerMessage.value = ''
  const query = ledgerQueryString()
  try {
    const [listRes, summaryRes] = await Promise.all([
      request(`/api/tenant/ledger?${query}`),
      request(`/api/tenant/ledger/summary?${query}`),
    ])
    if (!listRes.ok) throw new Error('租金台账读取失败')
    if (!summaryRes.ok) throw new Error('租金台账合计读取失败')
    const listPayload = await listRes.json()
    ledgerRows.value = listPayload.items ?? []
    ledgerTotal.value = listPayload.total ?? ledgerRows.value.length
    summary.value = await summaryRes.json()
  } catch (error) {
    ledgerMessage.value = error instanceof Error ? error.message : '租金台账读取失败'
  }
}

async function onFilePicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importing.value = true
  ledgerMessage.value = ''
  importResult.value = null
  try {
    const content = await readCsvText(file)
    const response = await request('/api/tenant/ledger/import-bills', {
      method: 'POST',
      body: JSON.stringify({ values: { file_name: file.name, content } }),
    })
    if (!response.ok) throw new Error(`接口返回 ${response.status}，账单未导入`)
    importResult.value = await response.json()
    await reloadLedger()
  } catch (error) {
    ledgerMessage.value = error instanceof Error ? error.message : '账单导入失败'
  } finally {
    importing.value = false
  }
}

// Excel 导出的 CSV 常见是 GBK，先按 UTF-8 试、乱码再按 GBK 解。
function readCsvText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const bytes = new Uint8Array(reader.result as ArrayBuffer)
      const decoder = new TextDecoder('utf-8', { fatal: true })
      try {
        resolve(decoder.decode(bytes))
      } catch {
        try {
          resolve(new TextDecoder('gbk').decode(bytes))
        } catch {
          reject(new Error('账单文件编码无法识别，请另存为 UTF-8 CSV 后重试'))
        }
      }
    }
    reader.onerror = () => reject(new Error('账单文件读取失败'))
    reader.readAsArrayBuffer(file)
  })
}

function exportLedger(format: 'csv' | 'json') {
  const query = new URLSearchParams(ledgerQueryString())
  query.set('format', format)
  window.open(`/api/tenant/ledger/export?${query.toString()}`, '_blank')
}

// --------------------------------------------------------------- 铺位
const booths = ref<BoothRow[]>([])
const boothFilter = reactive({ keyword: '', status: '' })

function resetBoothFilter() {
  boothFilter.keyword = ''
  boothFilter.status = ''
  void loadBooths()
}

async function loadBooths() {
  const query = new URLSearchParams()
  if (boothFilter.keyword) query.set('keyword', boothFilter.keyword)
  if (boothFilter.status) query.set('status', boothFilter.status)
  try {
    const response = await request(`/api/tenant/booths?${query.toString()}`)
    if (!response.ok) throw new Error('铺位状态读取失败')
    const payload = await response.json()
    booths.value = payload.items ?? []
  } catch {
    // 铺位查询失败不打断其它页签
  }
}

// --------------------------------------------------------------- 公共
function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  return Number.isFinite(amount) ? amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : String(value)
}

function switchTab(key: (typeof tabs)[number]['key']) {
  activeTab.value = key
}

onMounted(() => {
  void loadContracts()
  void reloadLedger()
  void loadBooths()
})
</script>
