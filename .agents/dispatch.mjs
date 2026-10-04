#!/usr/bin/env node
// Worker dispatcher for the Claude manager (see CLAUDE.md). No dependencies.
//
//   node .agents/dispatch.mjs run --agent codex|qwen --name <slug> --task-file <file>
//        [--task "<text>"] [--model <m>] [--effort low|medium|high] [--base <branch>] [--timeout-min 30]
//   node .agents/dispatch.mjs status
//   node .agents/dispatch.mjs cleanup --name <slug> [--force]
//
// Each worker gets its own git worktree (../<repo>-worktrees/<slug>) on branch agent/<slug>.
// The task goes to the worker on stdin (never through the command line). Whatever the worker
// changed is committed on that branch. Nothing is pushed or merged — the manager decides.
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { parseArgs } from 'node:util'

const DEFAULTS = {
  codex: { model: 'gpt-6.1-sol', effort: 'medium' },
  timeoutMin: 30
}
const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

function git(args, cwd) {
  const r = spawnSync('git', ['-c', 'core.quotepath=false', ...args], { cwd, encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`git ${args.join(' ')} failed: ${(r.stderr || r.stdout).trim()}`)
  return r.stdout.trim()
}

const repoRoot = git(['rev-parse', '--show-toplevel'], process.cwd())
const worktreesDir = path.join(path.dirname(repoRoot), `${path.basename(repoRoot)}-worktrees`)

function workerPrompt(task, branch) {
  return [
    `You are a worker agent. Work only in the current folder: a git worktree on branch ${branch}.`,
    '',
    'TASK:',
    task.trim(),
    '',
    'Rules:',
    '- Change only what the task needs. Do not touch files outside this folder.',
    '- Do not run git push, git merge, git checkout or git commit. The dispatcher commits your changes.',
    '- If the project has tests and you can run them, run the relevant ones and report the result honestly.',
    '- Finish with a short summary: files changed, how you verified, anything left or uncertain.'
  ].join('\n')
}

function resolveCodex() {
  const candidates = [
    process.env.CODEX_BIN,
    path.join(process.env.LOCALAPPDATA ?? '', 'Programs', 'OpenAI', 'Codex', 'bin', 'codex.exe')
  ].filter(Boolean)
  return candidates.find((p) => existsSync(p)) ?? 'codex'
}

function resolveQwen() {
  const entry =
    process.env.QWEN_CLI ??
    path.join(process.env.APPDATA ?? '', 'npm', 'node_modules', '@qwen-code', 'qwen-code', 'cli-entry.js')
  if (!existsSync(entry)) throw new Error(`Qwen Code not found at ${entry} (set QWEN_CLI)`)
  return entry
}

function runProcess(file, args, { cwd, input, timeoutMs }) {
  const started = Date.now()
  return new Promise((resolve) => {
    const child = spawn(file, args, { cwd, windowsHide: true })
    let stdout = ''
    let stderr = ''
    let timedOut = false
    child.stdout.setEncoding('utf8').on('data', (d) => (stdout += d))
    child.stderr.setEncoding('utf8').on('data', (d) => (stderr += d))
    const timer = setTimeout(() => {
      timedOut = true
      if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'])
      else child.kill('SIGKILL')
    }, timeoutMs)
    child.on('error', (e) => {
      clearTimeout(timer)
      resolve({ code: -1, stdout, stderr: stderr + e.message, timedOut, seconds: 0 })
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      resolve({ code: code ?? -1, stdout, stderr, timedOut, seconds: Math.round((Date.now() - started) / 1000) })
    })
    child.stdin.on('error', () => {})
    child.stdin.end(input)
  })
}

// The local GPU runs one model at a time: only one qwen worker at once.
function acquireQwenLock() {
  const lock = path.join(os.tmpdir(), 'qwen-worker.lock')
  if (existsSync(lock)) {
    const pid = Number(readFileSync(lock, 'utf8'))
    let alive = false
    try {
      process.kill(pid, 0)
      alive = true
    } catch {}
    if (alive) throw new Error(`another qwen worker is running (pid ${pid}); run qwen tasks one at a time`)
  }
  writeFileSync(lock, String(process.pid))
  return () => {
    try {
      unlinkSync(lock)
    } catch {}
  }
}

async function runWorker(o) {
  const agent = o.agent
  if (agent !== 'codex' && agent !== 'qwen') throw new Error('--agent must be codex or qwen')
  if (!SLUG_RE.test(o.name ?? '')) throw new Error('--name must be lowercase letters, digits and dashes')
  const task = o['task-file'] ? readFileSync(o['task-file'], 'utf8') : o.task
  if (!task || !task.trim()) throw new Error('give the task with --task-file <file> (preferred) or --task')

  const base = o.base ?? git(['branch', '--show-current'], repoRoot)
  const branch = `agent/${o.name}`
  const wt = path.join(worktreesDir, o.name)
  if (existsSync(wt)) throw new Error(`worktree already exists: ${wt} — use another --name or run cleanup`)
  mkdirSync(worktreesDir, { recursive: true })
  git(['worktree', 'add', '-q', '-b', branch, wt, base], repoRoot)

  const agentDir = path.join(wt, '.agent')
  mkdirSync(agentDir, { recursive: true })
  writeFileSync(path.join(agentDir, 'task.md'), task)
  const prompt = workerPrompt(task, branch)
  const timeoutMs = Number(o['timeout-min'] ?? DEFAULTS.timeoutMin) * 60_000

  let r
  let summary = ''
  if (agent === 'codex') {
    const summaryFile = path.join(agentDir, 'summary.md')
    const args = [
      'exec',
      '-C', wt,
      '--sandbox', 'workspace-write',
      '-m', o.model ?? DEFAULTS.codex.model,
      '-c', `model_reasoning_effort=${o.effort ?? DEFAULTS.codex.effort}`,
      '-o', summaryFile,
      '-'
    ]
    r = await runProcess(resolveCodex(), args, { cwd: wt, input: prompt, timeoutMs })
    summary = existsSync(summaryFile) ? readFileSync(summaryFile, 'utf8') : r.stdout.slice(-2000)
  } else {
    const release = acquireQwenLock()
    try {
      // auto-edit: file edits inside the worktree are approved; shell commands are not.
      const args = [resolveQwen(), '--approval-mode', 'auto-edit', '-o', 'json']
      if (o.model) args.push('-m', o.model)
      r = await runProcess(process.execPath, args, { cwd: wt, input: prompt, timeoutMs })
    } finally {
      release()
    }
    try {
      const parsed = JSON.parse(r.stdout)
      const result = (Array.isArray(parsed) ? parsed : [parsed]).find((x) => x?.type === 'result') ?? {}
      summary = String(result.result ?? '')
    } catch {
      summary = r.stdout.slice(-2000)
    }
  }
  writeFileSync(path.join(agentDir, 'worker.log'), `exit=${r.code} timedOut=${r.timedOut}\n--- stdout ---\n${r.stdout}\n--- stderr ---\n${r.stderr}`)

  let commit = null
  if (git(['status', '--porcelain'], wt)) {
    git(['add', '-A'], wt)
    git(['commit', '-q', '-m', `${o.name}: ${agent} worker`, '-m', `Worker: ${agent}\nTask: .agent/task.md (not committed)`], wt)
    commit = git(['rev-parse', '--short', 'HEAD'], wt)
  }
  const diffStat = git(['diff', '--stat', `${base}...${branch}`], wt)
  return {
    agent,
    name: o.name,
    branch,
    base,
    worktree: wt,
    exitCode: r.code,
    timedOut: r.timedOut,
    seconds: r.seconds,
    commit,
    diffStat: diffStat || '(no changes)',
    summary: summary.trim().slice(0, 3000),
    log: path.join(agentDir, 'worker.log')
  }
}

function status() {
  const out = git(['worktree', 'list', '--porcelain'], repoRoot)
  const base = git(['branch', '--show-current'], repoRoot)
  return out
    .split(/\r?\n\r?\n/)
    .map((block) => ({
      worktree: block.match(/^worktree (.+)$/m)?.[1],
      branch: block.match(/^branch refs\/heads\/(.+)$/m)?.[1]
    }))
    .filter((w) => w.branch?.startsWith('agent/'))
    .map((w) => ({
      ...w,
      aheadOfBase: Number(git(['rev-list', '--count', `${base}..${w.branch}`], repoRoot)),
      diffStat: git(['diff', '--shortstat', `${base}...${w.branch}`], repoRoot) || '(no changes)'
    }))
}

function cleanup(o) {
  if (!SLUG_RE.test(o.name ?? '')) throw new Error('--name is required')
  const wt = path.join(worktreesDir, o.name)
  git(['worktree', 'remove', ...(o.force ? ['--force'] : []), wt], repoRoot)
  return { removed: wt, branchKept: `agent/${o.name}` }
}

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    agent: { type: 'string' },
    name: { type: 'string' },
    task: { type: 'string' },
    'task-file': { type: 'string' },
    model: { type: 'string' },
    effort: { type: 'string' },
    base: { type: 'string' },
    'timeout-min': { type: 'string' },
    force: { type: 'boolean', default: false }
  }
})

try {
  const cmd = positionals[0]
  const result =
    cmd === 'run' ? await runWorker(values) : cmd === 'status' ? status() : cmd === 'cleanup' ? cleanup(values) : null
  if (result === null) throw new Error('usage: dispatch.mjs run|status|cleanup (see header)')
  console.log(JSON.stringify(result, null, 2))
} catch (e) {
  console.error(`dispatch: ${e.message}`)
  process.exit(1)
}
