import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Dropdown from './Dropdown'

function getTrigger(name) {
  return screen.getByRole('button', { name })
}

describe('Dropdown', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('is closed initially and opens on trigger click', async () => {
    const user = userEvent.setup()
    render(<Dropdown value="job_board" onChange={() => {}} options={['job_board', 'aggregator']} ariaLabel="Type" />)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

    await user.click(getTrigger('Type'))
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(getTrigger('Type')).toHaveAttribute('aria-expanded', 'true')
  })

  it('closes again on a second trigger click', async () => {
    const user = userEvent.setup()
    render(<Dropdown value="job_board" onChange={() => {}} options={['job_board', 'aggregator']} ariaLabel="Type" />)
    await user.click(getTrigger('Type'))
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.click(getTrigger('Type'))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes on an outside click', async () => {
    const user = userEvent.setup()
    render(
      <div>
        <Dropdown value="job_board" onChange={() => {}} options={['job_board', 'aggregator']} ariaLabel="Type" />
        <button type="button">elsewhere</button>
      </div>,
    )
    await user.click(getTrigger('Type'))
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'elsewhere' }))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('calls onChange with the clicked option value and closes the menu', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Dropdown value="job_board" onChange={onChange} options={['job_board', 'aggregator']} ariaLabel="Type" />)
    await user.click(getTrigger('Type'))
    await user.click(screen.getByRole('option', { name: 'Aggregator' }))
    expect(onChange).toHaveBeenCalledWith('aggregator')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('clears the value when the placeholder entry is picked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <Dropdown
        value="job_board"
        onChange={onChange}
        options={['job_board', 'aggregator']}
        placeholder="Any type"
        ariaLabel="Type"
      />,
    )
    await user.click(getTrigger('Type'))
    await user.click(screen.getByRole('option', { name: 'Any type' }))
    expect(onChange).toHaveBeenCalledWith(undefined)
  })

  it('shows the placeholder as the trigger label when no value is selected', () => {
    render(<Dropdown value={undefined} onChange={() => {}} options={['a', 'b']} placeholder="Pick one" ariaLabel="Field" />)
    expect(getTrigger('Field')).toHaveTextContent('Pick one')
  })

  describe('keyboard navigation', () => {
    it('opens on ArrowDown/ArrowUp/Enter/Space when closed', async () => {
      const user = userEvent.setup()
      render(<Dropdown value="a" onChange={() => {}} options={['a', 'b', 'c']} ariaLabel="Field" />)
      getTrigger('Field').focus()
      await user.keyboard('{ArrowDown}')
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    it('moves the active option with ArrowDown/ArrowUp and wraps around', async () => {
      const user = userEvent.setup()
      render(<Dropdown value="a" onChange={() => {}} options={['a', 'b', 'c']} ariaLabel="Field" />)
      getTrigger('Field').focus()
      await user.keyboard('{ArrowDown}') // open, active = selected ("a")
      const listbox = screen.getByRole('listbox')
      expect(within(listbox).getByRole('option', { name: 'A' })).toHaveAttribute('data-active', 'true')

      await user.keyboard('{ArrowDown}')
      expect(within(listbox).getByRole('option', { name: 'B' })).toHaveAttribute('data-active', 'true')

      await user.keyboard('{ArrowUp}')
      expect(within(listbox).getByRole('option', { name: 'A' })).toHaveAttribute('data-active', 'true')

      // wrap upward past the first entry
      await user.keyboard('{ArrowUp}')
      expect(within(listbox).getByRole('option', { name: 'C' })).toHaveAttribute('data-active', 'true')
    })

    it('Home/End jump to the first/last option', async () => {
      const user = userEvent.setup()
      render(<Dropdown value="a" onChange={() => {}} options={['a', 'b', 'c']} ariaLabel="Field" />)
      getTrigger('Field').focus()
      await user.keyboard('{ArrowDown}')
      const listbox = screen.getByRole('listbox')

      await user.keyboard('{End}')
      expect(within(listbox).getByRole('option', { name: 'C' })).toHaveAttribute('data-active', 'true')

      await user.keyboard('{Home}')
      expect(within(listbox).getByRole('option', { name: 'A' })).toHaveAttribute('data-active', 'true')
    })

    it('Enter picks the active option and calls onChange', async () => {
      const user = userEvent.setup()
      const onChange = vi.fn()
      render(<Dropdown value="a" onChange={onChange} options={['a', 'b', 'c']} ariaLabel="Field" />)
      getTrigger('Field').focus()
      await user.keyboard('{ArrowDown}') // open
      await user.keyboard('{ArrowDown}') // active -> b
      await user.keyboard('{Enter}')
      expect(onChange).toHaveBeenCalledWith('b')
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })

    it('Escape closes the menu and refocuses the trigger without picking anything', async () => {
      const user = userEvent.setup()
      const onChange = vi.fn()
      render(<Dropdown value="a" onChange={onChange} options={['a', 'b', 'c']} ariaLabel="Field" />)
      getTrigger('Field').focus()
      await user.keyboard('{ArrowDown}')
      expect(screen.getByRole('listbox')).toBeInTheDocument()
      await user.keyboard('{Escape}')
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      expect(onChange).not.toHaveBeenCalled()
      expect(getTrigger('Field')).toHaveFocus()
    })

    it('Escape does not bubble to a parent listener (it is captured and stopped)', async () => {
      const user = userEvent.setup()
      const parentHandler = vi.fn()
      render(
        // eslint-disable-next-line jsx-a11y/no-static-element-interactions
        <div onKeyDown={parentHandler}>
          <Dropdown value="a" onChange={() => {}} options={['a', 'b', 'c']} ariaLabel="Field" />
        </div>,
      )
      getTrigger('Field').focus()
      await user.keyboard('{ArrowDown}')
      expect(screen.getByRole('listbox')).toBeInTheDocument()
      parentHandler.mockClear()
      await user.keyboard('{Escape}')
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      expect(parentHandler).not.toHaveBeenCalled()
    })

    it('typeahead jumps to the first option whose label starts with the typed letter', async () => {
      const user = userEvent.setup()
      render(<Dropdown value="a" onChange={() => {}} options={['apple', 'banana', 'cherry']} ariaLabel="Field" />)
      getTrigger('Field').focus()
      await user.keyboard('{ArrowDown}') // open
      const listbox = screen.getByRole('listbox')
      await user.keyboard('c')
      expect(within(listbox).getByRole('option', { name: 'Cherry' })).toHaveAttribute('data-active', 'true')
    })

    it('Tab closes the menu without picking anything', async () => {
      const user = userEvent.setup()
      const onChange = vi.fn()
      render(
        <>
          <Dropdown value="a" onChange={onChange} options={['a', 'b', 'c']} ariaLabel="Field" />
          <button type="button">next</button>
        </>,
      )
      getTrigger('Field').focus()
      await user.keyboard('{ArrowDown}')
      expect(screen.getByRole('listbox')).toBeInTheDocument()
      await user.keyboard('{Tab}')
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      expect(onChange).not.toHaveBeenCalled()
    })
  })

  describe('regression: Dropdown rendered inside a <label>', () => {
    it('closes on option click instead of the label re-forwarding the click to the trigger and reopening it', async () => {
      const user = userEvent.setup()
      const onChange = vi.fn()
      render(
        <label>
          Type
          <Dropdown value="job_board" onChange={onChange} options={['job_board', 'aggregator']} ariaLabel="Type" />
        </label>,
      )
      await user.click(getTrigger('Type'))
      expect(screen.getByRole('listbox')).toBeInTheDocument()

      await user.click(screen.getByRole('option', { name: 'Aggregator' }))

      expect(onChange).toHaveBeenCalledTimes(1)
      expect(onChange).toHaveBeenCalledWith('aggregator')
      // The regression: a <label> forwards a click on non-form-control content
      // to the label's associated control (the trigger `<button>`), which used
      // to toggle `open` back to true immediately after `pick()` closed it.
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })
  })

  it('supports object options with a custom `value`/`label`', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <Dropdown
        value="b"
        onChange={onChange}
        options={[{ value: 'a', label: 'Alpha' }, { value: 'b', label: 'Beta' }]}
        ariaLabel="Field"
      />,
    )
    expect(getTrigger('Field')).toHaveTextContent('Beta')
    await user.click(getTrigger('Field'))
    await user.click(screen.getByRole('option', { name: 'Alpha' }))
    expect(onChange).toHaveBeenCalledWith('a')
  })

  it('is inert while disabled: click does not open the menu', async () => {
    const user = userEvent.setup()
    render(<Dropdown value="a" onChange={() => {}} options={['a', 'b']} disabled ariaLabel="Field" />)
    expect(getTrigger('Field')).toBeDisabled()
    await user.click(getTrigger('Field'));
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })
})
