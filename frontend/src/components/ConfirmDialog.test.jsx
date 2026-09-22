import { describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  ConfirmProvider,
  clearAllSuppressedConfirms,
  clearSuppressedConfirm,
  suppressedConfirms,
  useConfirm,
  useSuppressedConfirms,
} from './ConfirmDialog'

const STORAGE_KEY = 'opportunity-tracker.suppressed-confirms'

function Harness({ onResult, request }) {
  const confirm = useConfirm()
  return (
    <button
      type="button"
      onClick={async () => {
        const result = await confirm(request)
        onResult(result)
      }}
    >
      ask
    </button>
  )
}

function renderHarness(request, onResult = () => {}) {
  return render(
    <ConfirmProvider>
      <Harness request={request} onResult={onResult} />
    </ConfirmProvider>,
  )
}

describe('useConfirm', () => {
  it('throws when used outside a ConfirmProvider', () => {
    // React logs the thrown error to console.error (and jsdom logs the
    // "Uncaught" version too); expected noise for this one test, silenced so
    // the run's output stays readable.
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const Bare = () => {
      useConfirm()
      return null
    }
    expect(() => render(<Bare />)).toThrow('useConfirm must be used inside a ConfirmProvider')
    consoleSpy.mockRestore()
  })

  it('resolves true when Confirm is clicked', async () => {
    const user = userEvent.setup()
    const onResult = vi.fn()
    renderHarness({ title: 'Delete this?' }, onResult)
    await user.click(screen.getByRole('button', { name: 'ask' }))
    await user.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('resolves false when Cancel is clicked', async () => {
    const user = userEvent.setup()
    const onResult = vi.fn()
    renderHarness({ title: 'Delete this?' }, onResult)
    await user.click(screen.getByRole('button', { name: 'ask' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false))
  })

  it('resolves false when the scrim behind the dialog is clicked', async () => {
    const user = userEvent.setup()
    const onResult = vi.fn()
    const { container } = renderHarness({ title: 'Delete this?' }, onResult)
    await user.click(screen.getByRole('button', { name: 'ask' }))
    // eslint-disable-next-line testing-library/no-node-access
    await user.click(container.querySelector('[aria-hidden="true"]'))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false))
  })

  it('uses the custom confirm/cancel labels when given', async () => {
    const user = userEvent.setup()
    renderHarness({ title: 'Delete source?', confirmLabel: 'Delete source', cancelLabel: 'Keep it' })
    await user.click(screen.getByRole('button', { name: 'ask' }))
    expect(screen.getByRole('button', { name: 'Delete source' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keep it' })).toBeInTheDocument()
  })

  describe('focus management', () => {
    it('focuses Cancel on open, never the destructive/confirm button', async () => {
      const user = userEvent.setup()
      renderHarness({ title: 'Delete this?', confirmLabel: 'Delete' })
      await user.click(screen.getByRole('button', { name: 'ask' }))
      await waitFor(() => expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus())
      expect(screen.getByRole('button', { name: 'Delete' })).not.toHaveFocus()
    })

    it('traps Tab inside the dialog, wrapping from the last focusable element back to the first', async () => {
      const user = userEvent.setup()
      renderHarness({ title: 'Delete this?', confirmLabel: 'Delete', key: 'delete-opportunity' })
      await user.click(screen.getByRole('button', { name: 'ask' }))
      const cancel = await screen.findByRole('button', { name: 'Cancel' })
      expect(cancel).toHaveFocus()

      // The focusable set inside the dialog is [checkbox, Confirm, Cancel].
      // Shift+Tab off the first element (the checkbox) should wrap to the
      // last (Cancel) instead of leaving the dialog.
      const checkbox = screen.getByRole('checkbox')
      checkbox.focus()
      await user.tab({ shift: true })
      expect(cancel).toHaveFocus()

      // Tab off the last element (Cancel) should wrap back to the first
      // (the checkbox) instead of leaving the dialog.
      cancel.focus()
      await user.tab()
      expect(checkbox).toHaveFocus()
    })

    it('Escape cancels the dialog (resolves false) without needing a click', async () => {
      const user = userEvent.setup()
      const onResult = vi.fn()
      renderHarness({ title: 'Delete this?' }, onResult)
      await user.click(screen.getByRole('button', { name: 'ask' }))
      await screen.findByRole('alertdialog')
      await user.keyboard('{Escape}')
      await waitFor(() => expect(onResult).toHaveBeenCalledWith(false))
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    })
  })

  describe('"do not ask again"', () => {
    it('is not shown when the request has no key', async () => {
      const user = userEvent.setup()
      renderHarness({ title: 'Delete this?' })
      await user.click(screen.getByRole('button', { name: 'ask' }))
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    })

    it('persists the key to localStorage only when checked and confirmed', async () => {
      const user = userEvent.setup()
      renderHarness({ title: 'Delete this source?', key: 'delete-source' })
      await user.click(screen.getByRole('button', { name: 'ask' }))
      await user.click(screen.getByRole('checkbox'))
      await user.click(screen.getByRole('button', { name: 'Confirm' }))
      await waitFor(() => expect(suppressedConfirms()).toEqual(['delete-source']))
    })

    it('does NOT persist the key when confirmed without checking the box', async () => {
      const user = userEvent.setup()
      renderHarness({ title: 'Delete this source?', key: 'delete-source' })
      await user.click(screen.getByRole('button', { name: 'ask' }))
      await user.click(screen.getByRole('button', { name: 'Confirm' }))
      await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
      expect(suppressedConfirms()).toEqual([])
    })

    it('does NOT persist the key when cancelled, even with the box checked', async () => {
      const user = userEvent.setup()
      renderHarness({ title: 'Delete this source?', key: 'delete-source' })
      await user.click(screen.getByRole('button', { name: 'ask' }))
      await user.click(screen.getByRole('checkbox'))
      await user.click(screen.getByRole('button', { name: 'Cancel' }))
      await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
      expect(suppressedConfirms()).toEqual([])
    })

    it('suppresses later calls with the same key: resolves true immediately, no dialog shown', async () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['delete-source']))
      const user = userEvent.setup()
      const onResult = vi.fn()
      renderHarness({ title: 'Delete this source?', key: 'delete-source' }, onResult)
      await user.click(screen.getByRole('button', { name: 'ask' }))
      await waitFor(() => expect(onResult).toHaveBeenCalledWith(true))
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    })

    it('does not suppress a different key', async () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['delete-source']))
      const user = userEvent.setup()
      renderHarness({ title: 'Delete this application?', key: 'delete-application' })
      await user.click(screen.getByRole('button', { name: 'ask' }))
      expect(await screen.findByRole('alertdialog')).toBeInTheDocument()
    })

    it('clearSuppressedConfirm re-enables asking for just that key', () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['delete-source', 'delete-application']))
      clearSuppressedConfirm('delete-source')
      expect(suppressedConfirms()).toEqual(['delete-application'])
    })

    it('clearAllSuppressedConfirms resets every suppressed key', () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['delete-source', 'delete-application']))
      clearAllSuppressedConfirms()
      expect(suppressedConfirms()).toEqual([])
    })

    it('recovers instead of throwing when localStorage holds corrupt JSON', () => {
      localStorage.setItem(STORAGE_KEY, 'not json')
      expect(suppressedConfirms()).toEqual([])
    })
  })

  describe('useSuppressedConfirms', () => {
    it('reflects live changes made via writeSuppressed (the confirm-prefs-changed event)', async () => {
      function Listener() {
        const keys = useSuppressedConfirms()
        return <div data-testid="keys">{keys.join(',')}</div>
      }
      render(<Listener />)
      expect(screen.getByTestId('keys')).toHaveTextContent('')
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['delete-source']))
      act(() => {
        window.dispatchEvent(new Event('confirm-prefs-changed'))
      })
      await waitFor(() => expect(screen.getByTestId('keys')).toHaveTextContent('delete-source'))
    })
  })
})
