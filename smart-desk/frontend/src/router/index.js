import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import MeetingView from '../views/MeetingView.vue'

const routes = [
  { path: '/', name: 'home', component: HomeView },
  { path: '/meeting/:id', name: 'meeting', component: MeetingView },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
