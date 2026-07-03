import { test, expect } from '@playwright/test'

/**
 * E2E Tests: Chat Management
 *
 * Verifies: rename chat (modal), delete chat (modal + confirm), visibility toggle.
 */

const CHAT_ID = 'test-chat-mgmt'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/chats**', async (route, request) => {
    const url = request.url()
    const method = request.method()
    if (method === 'POST' && url.endsWith('/api/chats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: CHAT_ID, title: 'Management Test' }),
      })
    } else if (method === 'GET' && url.includes(`/api/chats/${CHAT_ID}`) && !url.includes('/visibility/') && !url.includes('/title/') && !url.includes('/votes/') && !url.includes('/messages/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: CHAT_ID,
          title: 'Management Test',
          isOwner: true,
          visibility: 'private',
          messages: [],
        }),
      })
    } else if (method === 'PATCH' && url.includes('/title/')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ title: 'New Chat Name' }) })
    } else if (method === 'DELETE' && url.includes(`/api/chats/${CHAT_ID}`)) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    } else if (method === 'GET' && url.includes('/api/chats')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
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

test('Rename Chat: opens modal, types new name, saves', async ({ page }) => {
  await goToChat(page)

  const titleBtn = page.locator('button', { hasText: 'Management Test' })
  await expect(titleBtn).toBeVisible({ timeout: 10000 })
  await titleBtn.click()

  const renameItem = page.getByRole('menuitem', { name: 'Rename' })
  await expect(renameItem).toBeVisible({ timeout: 5000 })
  await renameItem.click()

  // Rename modal heading should appear
  await expect(page.getByRole('heading', { name: 'Rename chat' })).toBeVisible({ timeout: 5000 })

  // Type new title
  const input = page.locator('input[placeholder="Chat title"]')
  await expect(input).toBeVisible({ timeout: 5000 })
  await input.fill('New Chat Name')

  // Click Save
  await page.getByRole('button', { name: 'Save' }).click()

  // Modal should close — use heading role to avoid toast ambiguity
  await expect(page.getByRole('heading', { name: 'Rename chat' })).not.toBeVisible({ timeout: 8000 })
})

test('Rename Chat: cancel button closes modal without renaming', async ({ page }) => {
  await goToChat(page)

  const titleBtn = page.locator('button', { hasText: 'Management Test' })
  await expect(titleBtn).toBeVisible({ timeout: 10000 })
  await titleBtn.click()

  const renameItem = page.getByRole('menuitem', { name: 'Rename' })
  await expect(renameItem).toBeVisible({ timeout: 5000 })
  await renameItem.click()

  await expect(page.getByRole('heading', { name: 'Rename chat' })).toBeVisible({ timeout: 5000 })

  // Click Cancel in the modal footer
  await page.getByRole('button', { name: 'Cancel' }).first().click()

  await expect(page.getByRole('heading', { name: 'Rename chat' })).not.toBeVisible({ timeout: 8000 })
})

test('Delete Chat: shows confirm modal, cancel keeps chat', async ({ page }) => {
  await goToChat(page)

  const titleBtn = page.locator('button', { hasText: 'Management Test' })
  await expect(titleBtn).toBeVisible({ timeout: 10000 })
  await titleBtn.click()

  const deleteItem = page.getByRole('menuitem', { name: 'Delete' })
  await expect(deleteItem).toBeVisible({ timeout: 5000 })
  await deleteItem.click()

  // Confirm modal Delete button should appear
  await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible({ timeout: 5000 })

  // Click Cancel on the confirm modal
  const cancelBtns = page.getByRole('button', { name: 'Cancel' })
  await cancelBtns.last().click()

  // Should still be on chat page
  await expect(page).toHaveURL(new RegExp(`/chat/${CHAT_ID}`))
})

test('Visibility: share button opens visibility modal', async ({ page }) => {
  await goToChat(page)

  const shareBtn = page.locator('button[aria-label="Share chat"]')
  await expect(shareBtn).toBeVisible({ timeout: 10000 })
  await shareBtn.click()

  // Modal heading should appear
  await expect(page.getByRole('heading', { name: 'Share chat' })).toBeVisible({ timeout: 5000 })

  // Close via Escape
  await page.keyboard.press('Escape')
  await page.waitForTimeout(1000)
  await expect(page.getByRole('heading', { name: 'Share chat' })).not.toBeVisible({ timeout: 5000 })
})
