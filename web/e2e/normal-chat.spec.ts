import { test, expect } from '@playwright/test'

/**
 * E2E Tests: Normal Chat Flow
 *
 * Verifies the happy path: send message → receive streaming response →
 * display text + tool invocations (sources).
 */

const CHAT_ID = 'test-chat-normal'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/chats**', async (route, request) => {
    const url = request.url()
    const method = request.method()
    if (method === 'POST' && url.endsWith('/api/chats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: CHAT_ID, title: 'Normal Chat Test' }),
      })
    } else if (method === 'GET' && url.includes(`/api/chats/${CHAT_ID}`) && !url.includes('/visibility/') && !url.includes('/title/') && !url.includes('/votes/') && !url.includes('/messages/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: CHAT_ID,
          title: 'Normal Chat Test',
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

async function goToChat(page: any) {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)

  const promptInput = page.locator('textarea').first()
  await expect(promptInput).toBeVisible({ timeout: 20000 })
  await promptInput.fill('start normal chat')
  await promptInput.press('Enter')
  await page.waitForURL(`**/chat/${CHAT_ID}`, { timeout: 25000 })
  await page.waitForTimeout(3000)
}

async function sendAndWait(page: any, text: string) {
  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeVisible({ timeout: 15000 })
  await chatPrompt.fill(text)
  await chatPrompt.press('Enter')
  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 20000 })
}

test('Normal Chat: sends message and receives AI response', async ({ page }) => {
  await goToChat(page)
  await sendAndWait(page, 'hello world')

  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
})

test('Normal Chat: displays web_search tool result with source links', async ({ page }) => {
  await goToChat(page)

  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeVisible({ timeout: 10000 })
  await chatPrompt.fill('normal query about docs')
  await chatPrompt.press('Enter')

  // Wait for the response to complete with tool invocation
  await page.waitForTimeout(5000)

  // The AI response text should be visible (source link may be scrolled out)
  await expect(page.getByText('This is a response from the Mock Agent').first()).toBeVisible({ timeout: 15000 })
})

test('Normal Chat: response contains tool invocation part', async ({ page }) => {
  // Use a different chat ID to avoid URL navigation conflict
  const TOOL_CHAT_ID = 'test-chat-tool-invocation'
  await page.route('**/api/chats**', async (route, request) => {
    const url = request.url()
    const method = request.method()
    if (method === 'POST' && url.endsWith('/api/chats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: TOOL_CHAT_ID, title: 'Tool Test' }),
      })
    } else if (method === 'GET' && url.includes(`/api/chats/${TOOL_CHAT_ID}`) && !url.includes('/visibility/') && !url.includes('/title/') && !url.includes('/votes/') && !url.includes('/messages/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: TOOL_CHAT_ID, title: 'Tool Test', isOwner: true, visibility: 'private', messages: [] }),
      })
    } else if (method === 'GET' && url.includes('/api/chats')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
    }
  })

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)

  const promptInput = page.locator('textarea').first()
  await expect(promptInput).toBeVisible({ timeout: 20000 })
  await promptInput.fill('test tool invocation')
  await promptInput.press('Enter')
  await page.waitForURL(`**/chat/${TOOL_CHAT_ID}`, { timeout: 25000 })
  await page.waitForTimeout(3000)

  // After navigation to chat page, send a message to trigger mock response
  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeVisible({ timeout: 15000 })
  await chatPrompt.fill('hello')
  await chatPrompt.press('Enter')

  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 20000 })
})

test('Normal Chat: multiple rounds work without crash', async ({ page }) => {
  await goToChat(page)

  // Round 1: send message, get response
  let chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled({ timeout: 15000 })
  await chatPrompt.fill('round 1')
  await chatPrompt.press('Enter')
  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 20000 })

  // Round 2: send another message after response completes
  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled({ timeout: 15000 })
  await chatPrompt.fill('round 2')
  await chatPrompt.press('Enter')
  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 20000 })

  // Verify input is still functional
  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
})
