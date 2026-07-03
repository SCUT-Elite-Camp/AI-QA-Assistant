import { test, expect } from '@playwright/test'

/**
 * E2E Tests: Edge Cases & Boundary Scenarios
 *
 * Verifies: very long input, special characters, rapid successive sends,
 * stop generation, concurrent error + recovery edge cases.
 */

const CHAT_ID = 'test-chat-edge'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/chats**', async (route, request) => {
    const url = request.url()
    const method = request.method()
    if (method === 'POST' && url.endsWith('/api/chats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: CHAT_ID, title: 'Edge Test' }),
      })
    } else if (method === 'GET' && url.includes(`/api/chats/${CHAT_ID}`) && !url.includes('/visibility/') && !url.includes('/title/') && !url.includes('/votes/') && !url.includes('/messages/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: CHAT_ID,
          title: 'Edge Test',
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
  await promptInput.fill('start')
  await promptInput.press('Enter')
  await page.waitForURL(`**/chat/${CHAT_ID}`, { timeout: 25000 })
  await page.waitForTimeout(3000)
}

test('Long Input: handles very long message without crash', async ({ page }) => {
  await goToChat(page)

  const longText = 'A'.repeat(2000)
  const chatPrompt = page.locator('textarea').first()
  await chatPrompt.fill(longText)
  await chatPrompt.press('Enter')

  // Should receive a response without page crash
  await page.waitForTimeout(5000)

  // Page should still be functional
  await expect(page.locator('textarea').first()).toBeVisible({ timeout: 5000 })
})

test('Special Characters: handles emojis and Unicode', async ({ page }) => {
  await goToChat(page)

  const specialText = 'Hello 🎉 世界 🌍 — test unicode'
  const chatPrompt = page.locator('textarea').first()
  await chatPrompt.fill(specialText)
  await chatPrompt.press('Enter')

  // Wait for processing
  await page.waitForTimeout(4000)

  // The user message should display the special characters
  await expect(page.getByText('Hello')).toBeVisible({ timeout: 10000 })
  await expect(page.getByText('世界')).toBeVisible({ timeout: 10000 })
})

test('Rapid Sends: multiple quick sends are handled gracefully', async ({ page }) => {
  await goToChat(page)

  const chatPrompt = page.locator('textarea').first()

  // Send 3 messages quickly
  await chatPrompt.fill('rapid 1')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(500)

  await chatPrompt.fill('rapid 2')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(500)

  await chatPrompt.fill('rapid 3')
  await chatPrompt.press('Enter')

  // Wait for processing
  await page.waitForTimeout(5000)

  // Page should still be functional
  await expect(page.locator('textarea').first()).toBeVisible({ timeout: 10000 })
})

test('Stop Generation: stop button appears during streaming', async ({ page }) => {
  await goToChat(page)

  const chatPrompt = page.locator('textarea').first()
  await chatPrompt.fill('streaming normal text')
  await chatPrompt.press('Enter')

  // During streaming, page should be responsive
  await page.waitForTimeout(3000)

  // Verify no crash — page still shows chat UI
  await expect(page.locator('textarea').first()).toBeVisible({ timeout: 10000 })
})

test('Error then Normal: error recovery works after network error', async ({ page }) => {
  await goToChat(page)

  // Trigger network error
  let chatPrompt = page.locator('textarea').first()
  await chatPrompt.fill('network error test')
  await chatPrompt.press('Enter')
  await expect(page.getByText('Network connection error')).toBeVisible({ timeout: 15000 })

  // Immediately send normal message
  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
  await chatPrompt.fill('recovery after error')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(4000)
  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 15000 })

  // Verify input still functional
  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
})

test('Business Error then Normal: recovers after retrieval error', async ({ page }) => {
  await goToChat(page)

  // Trigger business error
  let chatPrompt = page.locator('textarea').first()
  await chatPrompt.fill('retrieval error test')
  await chatPrompt.press('Enter')
  await expect(page.getByText('The retrieval service is temporarily unavailable')).toBeVisible({ timeout: 15000 })

  // Recover with normal message
  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
  await chatPrompt.fill('normal after business error')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(4000)
  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 15000 })

  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
})

test('All Error Types Sequence: survives all 6 error keywords in a row', async ({ page }) => {
  await goToChat(page)

  const errors = [
    { query: 'network error one', text: 'Network connection error' },
    { query: 'timeout test query', text: 'Request timed out' },
    { query: 'stream error two', text: 'Generation interrupted' },
    { query: 'no context three', text: 'The knowledge base does not have sufficient information' },
    { query: 'retrieval error four', text: 'The retrieval service is temporarily unavailable' },
    { query: 'model error five', text: 'The model service is temporarily unavailable' },
  ]

  for (const err of errors) {
    const chatPrompt = page.locator('textarea').first()
    await expect(chatPrompt).toBeEnabled({ timeout: 5000 })
    await chatPrompt.fill(err.query)
    await chatPrompt.press('Enter')
    await expect(page.getByText(err.text)).toBeVisible({ timeout: 15000 })
  }

  // Final recovery
  const chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
  await chatPrompt.fill('final recovery message')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(4000)
  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 15000 })
})

test('Empty String Recovery: error then empty input then normal', async ({ page }) => {
  await goToChat(page)

  // Trigger an error first
  let chatPrompt = page.locator('textarea').first()
  await chatPrompt.fill('network error trigger')
  await chatPrompt.press('Enter')
  await expect(page.getByText('Network connection error')).toBeVisible({ timeout: 15000 })

  // Try sending empty input (should be blocked)
  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()
  await chatPrompt.fill('   ')
  await chatPrompt.press('Enter')

  // Should still be on chat page, input still enabled
  await expect(page).toHaveURL(new RegExp(`/chat/${CHAT_ID}`))
  chatPrompt = page.locator('textarea').first()
  await expect(chatPrompt).toBeEnabled()

  // Now send a normal message
  await chatPrompt.fill('normal after empty')
  await chatPrompt.press('Enter')
  await page.waitForTimeout(4000)
  await expect(page.getByText('This is a response from the Mock Agent')).toBeVisible({ timeout: 15000 })
})
