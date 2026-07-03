import { test, expect } from '@playwright/test'

/**
 * E2E Tests: Message Interaction Actions
 *
 * Verifies: copy, thumbs-up/down vote, regenerate, edit message.
 */

const CHAT_ID = 'test-chat-actions'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/chats**', async (route, request) => {
    const url = request.url()
    const method = request.method()
    if (method === 'POST' && url.endsWith('/api/chats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: CHAT_ID, title: 'Actions Test' }),
      })
    } else if (method === 'GET' && url.includes(`/api/chats/${CHAT_ID}`) && !url.includes('/visibility/') && !url.includes('/title/') && !url.includes('/votes/') && !url.includes('/messages/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: CHAT_ID,
          title: 'Actions Test',
          isOwner: true,
          visibility: 'private',
          messages: [],
        }),
      })
    } else if (method === 'GET' && url.includes('/api/chats')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    } else if (method === 'DELETE' && url.includes('/messages/')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    } else if (method === 'POST' && url.includes('/votes/')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
    }
  })
})

async function goToChat(page: any) {
  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(2000)

  const promptInput = page.locator('textarea').first()
  await expect(promptInput).toBeVisible({ timeout: 15000 })
  await promptInput.fill('start')
  await promptInput.press('Enter')
  await page.waitForURL(`**/chat/${CHAT_ID}`, { timeout: 20000 })
  await page.waitForTimeout(2000)
}

async function sendAndWaitForResponse(page: any, text: string) {
  const chatPrompt = page.locator('textarea').first()
  await chatPrompt.fill(text)
  await chatPrompt.press('Enter')
  // Wait for the response to complete (status goes back to ready)
  await expect(page.locator('text=Mock Agent')).toBeVisible({ timeout: 15000 })
}

test('Copy Response: copy button is visible on assistant message', async ({ page }) => {
  await goToChat(page)
  await sendAndWaitForResponse(page, 'normal query')

  const copyBtn = page.locator('button[aria-label="Copy response"]')
  await expect(copyBtn).toBeVisible({ timeout: 10000 })
})

test('Vote: thumbs-up button works', async ({ page }) => {
  await goToChat(page)
  await sendAndWaitForResponse(page, 'normal query')

  const thumbsUp = page.locator('button[aria-label="Good response"]')
  await expect(thumbsUp).toBeVisible({ timeout: 10000 })
  await thumbsUp.click()
  // Should not crash
  await expect(thumbsUp).toBeVisible({ timeout: 5000 })
})

test('Vote: thumbs-down button works', async ({ page }) => {
  await goToChat(page)
  await sendAndWaitForResponse(page, 'normal query')

  const thumbsDown = page.locator('button[aria-label="Bad response"]')
  await expect(thumbsDown).toBeVisible({ timeout: 10000 })
  await thumbsDown.click()
  await expect(thumbsDown).toBeVisible({ timeout: 5000 })
})

test('Regenerate: regenerate button triggers new response', async ({ page }) => {
  await goToChat(page)
  await sendAndWaitForResponse(page, 'normal query')

  const regenerateBtn = page.locator('button[aria-label="Regenerate response"]')
  await expect(regenerateBtn).toBeVisible({ timeout: 10000 })
  await regenerateBtn.click()

  // Wait for new response
  await page.waitForTimeout(3000)
  await expect(page.locator('text=Mock Agent')).toBeVisible({ timeout: 15000 })
})

test('Edit Message: edit user message and resubmit', async ({ page }) => {
  await goToChat(page)
  await sendAndWaitForResponse(page, 'original message')

  // Find and click edit button on the user message
  const editBtn = page.locator('button[aria-label="Edit message"]')
  await expect(editBtn).toBeVisible({ timeout: 10000 })
  await editBtn.click()

  // Edit textarea should appear
  const editTextarea = page.locator('textarea').first()
  await expect(editTextarea).toBeVisible({ timeout: 5000 })

  // Clear and type new text
  await editTextarea.fill('edited message content')

  // Click Save
  await page.getByRole('button', { name: 'Save' }).click()

  // New response should appear
  await page.waitForTimeout(3000)
  await expect(page.locator('text=Mock Agent')).toBeVisible({ timeout: 15000 })
})
