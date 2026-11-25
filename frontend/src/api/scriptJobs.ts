import { api } from './client'
import type { components } from './schema.gen'

export type ScriptJob = components['schemas']['ScriptJobView']
export type ScriptJobUpdate = components['schemas']['ScriptJobUpdate']
export type ScriptJobRunStarted = components['schemas']['ScriptJobRunStarted']
export type SiteSessionStatus = components['schemas']['SiteSessionStatus']

export function listScriptJobs() {
  return api.get<{ items: ScriptJob[] }>('/script-jobs')
}

export function updateScriptJob(jobName: string, body: ScriptJobUpdate) {
  return api.put<ScriptJob>(`/script-jobs/${jobName}`, body)
}

export function startScriptJobRun(jobName: string, dryRun: boolean) {
  return api.post<ScriptJobRunStarted>(`/script-jobs/${jobName}/runs`, { dry_run: dryRun })
}

export function updateSiteSession(cookie: string, userAgent: string) {
  return api.put<SiteSessionStatus>('/script-jobs/sehuatang/site-session', { cookie, user_agent: userAgent })
}
