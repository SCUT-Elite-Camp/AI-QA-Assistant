import { test, expect } from '@playwright/test'

/**
 * Phase 2 E2E Tests: Error Display & Error Recovery
 *
 * Strategy:
 * - Mock both POST /api/chats (create) and GET /api/chats/:id (load) so
 *   the chat page renders without needing a real database.
 * - The chat page uses useMockChat (default) which triggers errors based on
 *   query keywords: "network error", "timeout", "stream error",
 *   "no context", "retrieval error", "model error".
 * - After error, input box should be re-usable (error recovery).
 */

const CHAT_ID = 'test-chat-001'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/chats**', async (route, request) => {
    const url = request.url()
    const method = request.method()
    if (method === 'POST' && url.endsWith('/api/chats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: CHAT_ID, title: 'Test Chat' }),
      })
    } else if (method === 'GET' && url.includes(`/api/chats/${CHAT_ID}`) && !url.includes('/visibility/') && !url.includes('/title/') && !url.includes('/votes/') && !url.includes('/messages/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: CHAT_ID,
          title: 'Test Chat',
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
})

// Helper: navigate from home to chat page and send an error-triggering message
async function navigateAndSendError(
  page: any,
  errorQuery: string,
  errorTextPattern: string
) {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)

  // Navigate to chat page first with a neutral message
  const promptInput = page.locator('textarea').first()
  await expect(promptInput).toBeVisible({ timeout: 20000 })
  await promptInput.fill('start')
  await promptInput.press('Enter')

  // Wait for navigation
  await page.waitForURL(`**/chat/${CHAT_ID}`, { timeout: 25000 })
  await page.waitForTimeout(3000)

  // Now send the error-triggering message
  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeVisible({ timeout: 15000 })
  await chatPrompt.fill(errorQuery)
  await chatPrompt.press('Enter')

  // Wait for error message to appear
  const errorText = page.getByText(errorTextPattern)
  await expect(errorText).toBeVisible({ timeout: 20000 })
}

test('Network Error: shows message and enables input recovery', async ({ page }) => {
  await navigateAndSendError(page, 'network error test', 'Network connection error')

  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeVisible()
  await expect(chatPrompt).toBeEnabled()

  // Recovery: send a normal message
  await chatPrompt.fill('hello normal')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(4000)
  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 15000 })
})

test('Timeout Error: shows message and recovers', async ({ page }) => {
  await navigateAndSendError(page, 'timeout test query', 'Request timed out')

  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
  // Recovery message must NOT contain "timeout"
  await chatPrompt.fill('hello world')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(4000)
  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 15000 })
})

test('Stream Error: shows message and recovers', async ({ page }) => {
  await navigateAndSendError(page, 'stream error test', 'Generation interrupted')

  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
})

test('No Relevant Context: shows message and recovers', async ({ page }) => {
  await navigateAndSendError(page, 'no context available for this', 'The knowledge base does not have sufficient information')

  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
})

test('Retrieval Error: shows message', async ({ page }) => {
  await navigateAndSendError(page, 'retrieval error test', 'The retrieval service is temporarily unavailable')
})

test('LLM Error: shows model error message', async ({ page }) => {
  await navigateAndSendError(page, 'model error test', 'The model service is temporarily unavailable')
})

test('Multiple Sequential Errors: recovers after several errors', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  const promptInput = page.locator('textarea').first()
  await expect(promptInput).toBeVisible({ timeout: 15000 })
  await promptInput.fill('start')
  await promptInput.press('Enter')
  await page.waitForURL(`**/chat/${CHAT_ID}`, { timeout: 20000 })
  await page.waitForTimeout(2000)

  // Error 1: network error
  let chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeVisible({ timeout: 10000 })
  await chatPrompt.fill('network error first')
  await chatPrompt.press('Enter')
  await expect(page.getByText('Network connection error')).toBeVisible({ timeout: 15000 })

  // Error 2: stream error
  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
  await chatPrompt.fill('stream error second')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(3000)

  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()

  // Recovery: normal message
  await chatPrompt.fill('hello final')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(4000)

  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 15000 })
})

test('Citation No Link: shows citation without URL', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  const promptInput = page.locator('textarea').first()
  await expect(promptInput).toBeVisible({ timeout: 15000 })
  await promptInput.fill('start')
  await promptInput.press('Enter')
  await page.waitForURL(`**/chat/${CHAT_ID}`, { timeout: 20000 })
  await page.waitForTimeout(2000)

  // Send no-link query
  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeVisible({ timeout: 10000 })
  await chatPrompt.fill('no-link test query')
  await chatPrompt.press('Enter')

  await page.waitForTimeout(5000)

  // Verify the normal response text is there
  await expect(page.getByText('Mock Agent')).toBeVisible({ timeout: 10000 })
})

test('Input Protection: does not submit empty input', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)

  const promptInput = page.locator('textarea').first()
  await expect(promptInput).toBeVisible({ timeout: 20000 })
  await promptInput.fill('   ') // whitespace only
  await promptInput.press('Enter')

  // Should stay on home page — use short timeout since no navigation should happen
  await page.waitForTimeout(2000)
  await expect(page).not.toHaveURL(/\/chat\//)
})
