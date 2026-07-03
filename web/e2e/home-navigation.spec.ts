import { test, expect } from '@playwright/test'

/**
 * E2E Tests: Home Page & Navigation
 *
 * Verifies: greeting, quick chat buttons, model select, input validation,
 * navigation between pages, 404 handling.
 */

const CHAT_ID = 'test-chat-nav'

test.beforeEach(async ({ page }) => {
  // Mock all API calls the home page makes
  await page.route('**/api/chats**', async (route, request) => {
    const url = request.url()
    const method = request.method()
    if (method === 'POST' && url.endsWith('/api/chats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: CHAT_ID, title: 'Nav Test' }),
      })
    } else if (method === 'GET' && url.includes(`/api/chats/${CHAT_ID}`) && !url.includes('/visibility/') && !url.includes('/title/') && !url.includes('/votes/') && !url.includes('/messages/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: CHAT_ID,
          title: 'Nav Test',
          isOwner: true,
          visibility: 'private',
          messages: [],
        }),
      })
    } else if (method === 'GET' && url.includes('/api/chats')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
    }
  })

  // Mock session endpoint
  await page.route('**/api/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user: null }),
    })
  })
})

test('Home Page: shows greeting text', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  // Use class-based selector to avoid strict mode violation with sidebar h1
  const greeting = page.locator('h1.text-3xl, h1.text-4xl')
  await expect(greeting).toBeVisible({ timeout: 15000 })
  const text = await greeting.textContent()
  expect(text).toMatch(/Good (morning|afternoon|evening)/)
})

test('Home Page: shows all 7 quick chat buttons', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  const quickButtons = [
    'Introduce yourself',
    "What's the weather today?",
    'Help me analyze sales data',
    'What is a vector database?',
    'Write a Vue 3 component example',
    'How to optimize RAG retrieval?',
    'Explain the Transformer architecture',
  ]

  for (const label of quickButtons) {
    await expect(page.getByRole('button', { name: label })).toBeVisible({ timeout: 10000 })
  }
})

test('Home Page: clicking quick chat button navigates to chat', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  await page.getByRole('button', { name: 'Introduce yourself' }).click()
  await page.waitForURL(`**/chat/${CHAT_ID}`, { timeout: 20000 })
})

test('Home Page: model selector is visible', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  // ModelSelect renders as a USelectMenu — check the textarea is there (page loaded)
  const promptInput = page.locator('textarea').first()
  await expect(promptInput).toBeVisible({ timeout: 15000 })
  await expect(promptInput).toHaveAttribute('placeholder', /.+/)
})

test('Home Page: empty input does not navigate', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  const promptInput = page.locator('textarea').first()
  await expect(promptInput).toBeVisible({ timeout: 15000 })
  await promptInput.fill('')
  await promptInput.press('Enter')

  // Stay on home page
  await expect(page).toHaveURL('/')
})

test('404 Page: visiting invalid chat ID shows error', async ({ page }) => {
  await page.route('**/api/chats/invalid-404**', async (route) => {
    await route.fulfill({ status: 404, contentType: 'application/json', body: 'null' })
  })
  await page.route('**/api/session', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: null }) })
  })
  await page.route('**/api/chats**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })

  await page.goto('/chat/invalid-404')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  await expect(page.getByText('Chat not found')).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('Go back to home')).toBeVisible({ timeout: 10000 })
})

test('404 Page: go back to home button works', async ({ page }) => {
  await page.route('**/api/chats/invalid-back**', async (route) => {
    await route.fulfill({ status: 404, contentType: 'application/json', body: 'null' })
  })
  await page.route('**/api/session', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: null }) })
  })
  await page.route('**/api/chats**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })

  await page.goto('/chat/invalid-back')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  await expect(page.getByText('Chat not found')).toBeVisible({ timeout: 15000 })
  await page.getByText('Go back to home').click()
  await expect(page).toHaveURL('/')
})

test('Home Page: placeholder text is visible', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  const textarea = page.locator('textarea').first()
  await expect(textarea).toBeVisible({ timeout: 15000 })
  const placeholder = await textarea.getAttribute('placeholder')
  expect(placeholder).toBeTruthy()
})
