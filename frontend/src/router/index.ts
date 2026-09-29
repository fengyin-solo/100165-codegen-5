import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '@/views/Dashboard.vue'
const Flight = () => import('@/views/flight/index.vue')
const Stand = () => import('@/views/stand/index.vue')
const Apron = () => import('@/views/apron/index.vue')
const Bridge = () => import('@/views/bridge/index.vue')
const Deicing = () => import('@/views/deicing/index.vue')
const Fueling = () => import('@/views/fueling/index.vue')
const Baggage = () => import('@/views/baggage/index.vue')
const Cargo = () => import('@/views/cargo/index.vue')
const Catering = () => import('@/views/catering/index.vue')
const Shuttle = () => import('@/views/shuttle/index.vue')
const Towing = () => import('@/views/towing/index.vue')
const Loadsheet = () => import('@/views/loadsheet/index.vue')
const Permit = () => import('@/views/permit/index.vue')
const Gse = () => import('@/views/gse/index.vue')
const Safety = () => import('@/views/safety/index.vue')
const Agreement = () => import('@/views/agreement/index.vue')
const Settlement = () => import('@/views/settlement/index.vue')
const Training = () => import('@/views/training/index.vue')
const Tenant = () => import('@/views/tenant/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/flight', name: 'flight', component: Flight },
    { path: '/stand', name: 'stand', component: Stand },
    { path: '/apron', name: 'apron', component: Apron },
    { path: '/bridge', name: 'bridge', component: Bridge },
    { path: '/deicing', name: 'deicing', component: Deicing },
    { path: '/fueling', name: 'fueling', component: Fueling },
    { path: '/baggage', name: 'baggage', component: Baggage },
    { path: '/cargo', name: 'cargo', component: Cargo },
    { path: '/catering', name: 'catering', component: Catering },
    { path: '/shuttle', name: 'shuttle', component: Shuttle },
    { path: '/towing', name: 'towing', component: Towing },
    { path: '/loadsheet', name: 'loadsheet', component: Loadsheet },
    { path: '/permit', name: 'permit', component: Permit },
    { path: '/gse', name: 'gse', component: Gse },
    { path: '/safety', name: 'safety', component: Safety },
    { path: '/agreement', name: 'agreement', component: Agreement },
    { path: '/settlement', name: 'settlement', component: Settlement },
    { path: '/training', name: 'training', component: Training },
    { path: '/tenant', name: 'tenant', component: Tenant },
  ],
})

export default router
