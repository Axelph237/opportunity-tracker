import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { createEvent, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DraftCanvas from './DraftCanvas'

const bullet = (ref, text, id) => ({ ref, text, source_bullet_id: id, source_text: text })

const BODY = {
  sections: [
    {
      ref: 's1',
      label: 'Experience',
      bullet_style: 'bullets',
      placements: [
        {
          ref: 'p1',
          entry_id: 1,
          kind: 'experience',
          title: 'Research Assistant',
          organization: 'Fermilab',
          dates: 'Jun 2026 -- Sep 2026',
          bullets: [bullet('b1', 'Built the DAQ pipeline', 11), bullet('b2', 'Halved calibration time', 12)],
        },
        { ref: 'p2', entry_id: 2, kind: 'experience', title: 'Teaching Assistant', bullets: [] },
      ],
    },
  ],
}

const ENTRY = {
  id: 7,
  kind: 'project',
  title: 'Delphi',
  organization: null,
  detail: 'Rust, WASM',
  start_date: '2026',
  end_date: null,
  is_current: true,
  url: null,
  bullets: [{ id: 21, text: 'Shipped a WASM renderer' }],
}

/** Controlled from the outside, like the page: assert both the write and the screen. */
function Harness({ initial = BODY, onChange, ...props }) {
  const [body, setBody] = useState(initial)
  return (
    <DraftCanvas
      body={body}
      onChange={(next) => {
        onChange?.(next)
        setBody(next)
      }}
      {...props}
    />
  )
}

function setup(props = {}) {
  const onChange = vi.fn()
  render(<Harness onChange={onChange} {...props} />)
  return onChange
}

const transfer = () => ({ setData: vi.fn(), getData: vi.fn(), dropEffect: '', effectAllowed: '' })

// jsdom has no DragEvent and so no DataTransfer; the components only set data
// and an effect on it, so a stub with those is enough.
const drag = (from, onto, { drop = true } = {}) => {
  const dataTransfer = transfer()
  fireEvent.dragStart(from, { dataTransfer })
  fireEvent.dragEnter(onto, { dataTransfer })
  fireEvent.dragOver(onto, { dataTransfer })
  if (drop) fireEvent.drop(onto, { dataTransfer })
  fireEvent.dragEnd(from, { dataTransfer })
}

const row = (text) => screen.getByText(text).closest('li')
const bulletsOf = (placementRef) =>
  [...document.querySelectorAll(`[data-placement="${placementRef}"] li`)].map((li) => li.textContent)
const placements = () =>
  [...document.querySelectorAll('[data-placement]')].map((node) => node.getAttribute('data-placement'))

describe('DraftCanvas / what it shows', () => {
  it('lays the resume out as sections, records and bullets', () => {
    setup()
    expect(screen.getByDisplayValue('Experience')).toBeInTheDocument()
    expect(screen.getByText('Research Assistant')).toBeInTheDocument()
    expect(screen.getByText('Fermilab · Jun 2026 -- Sep 2026')).toBeInTheDocument()
    expect(bulletsOf('p1')).toEqual(['Built the DAQ pipeline', 'Halved calibration time'])
  })

  it('says what to do with an empty draft rather than showing an empty box', () => {
    setup({ initial: { sections: [] } })
    expect(screen.getByText(/drag a record over from your bank/i)).toBeInTheDocument()
  })

  it('marks the ad’s keywords inside the bullets, leaving the sentence intact', () => {
    setup({ terms: ['DAQ'] })
    const mark = document.querySelector('[data-placement="p1"] mark')
    expect(mark).toHaveTextContent('DAQ')
    expect(mark.closest('li')).toHaveTextContent('Built the DAQ pipeline')
  })

  it('marks nothing when the ad asks for none of it', () => {
    setup({ terms: ['Kubernetes'] })
    expect(document.querySelector('mark')).toBeNull()
  })
})

describe('DraftCanvas / reordering bullets by drag', () => {
  it('moves a bullet and writes the new order back', () => {
    const onChange = setup()
    drag(row('Halved calibration time'), row('Built the DAQ pipeline'))

    expect(bulletsOf('p1')).toEqual(['Halved calibration time', 'Built the DAQ pipeline'])
    const written = onChange.mock.calls.at(-1)[0]
    expect(written.sections[0].placements[0].bullets.map((item) => item.ref)).toEqual(['b2', 'b1'])
  })

  it('rearranges under the pointer before the drop, so the drag shows what it will do', () => {
    setup()
    const dataTransfer = transfer()
    fireEvent.dragStart(row('Halved calibration time'), { dataTransfer })
    fireEvent.dragEnter(row('Built the DAQ pipeline'), { dataTransfer })
    expect(bulletsOf('p1')).toEqual(['Halved calibration time', 'Built the DAQ pipeline'])
  })

  it('puts everything back when the drag is abandoned', () => {
    // The list has been rearranging all along, so stopping is not enough.
    const onChange = setup()
    drag(row('Halved calibration time'), row('Built the DAQ pipeline'), { drop: false })

    expect(bulletsOf('p1')).toEqual(['Built the DAQ pipeline', 'Halved calibration time'])
    expect(onChange).not.toHaveBeenCalled()
  })

  it('writes nothing when a bullet is dropped back where it started', () => {
    const onChange = setup()
    drag(row('Built the DAQ pipeline'), row('Built the DAQ pipeline'))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('does not set the record it sits in dragging as well', () => {
    // A bullet sits inside a record that is itself draggable, so the one
    // dragstart reaches both unless it is stopped. Two lists rearranging at
    // once under one pointer is the symptom.
    setup()
    fireEvent.dragStart(row('Halved calibration time'), { dataTransfer: transfer() })
    expect(document.querySelector('[data-placement="p1"]')).not.toHaveClass('opacity-40')
    expect(row('Halved calibration time')).toHaveClass('opacity-40')
  })

  it('leaves the records in their own order', () => {
    setup()
    drag(row('Halved calibration time'), row('Built the DAQ pipeline'))
    expect(placements()).toEqual(['p1', 'p2'])
  })

  it('attaches drag data, which Firefox needs before it will start a drag at all', () => {
    setup()
    const dataTransfer = transfer()
    fireEvent.dragStart(row('Halved calibration time'), { dataTransfer })
    expect(dataTransfer.setData).toHaveBeenCalledWith('text/plain', 'b2')
  })

  it('cancels dragover, without which the browser never fires a drop at all', () => {
    setup()
    const dataTransfer = transfer()
    fireEvent.dragStart(row('Halved calibration time'), { dataTransfer })
    const over = createEvent.dragOver(row('Built the DAQ pipeline'), { dataTransfer })
    fireEvent(row('Built the DAQ pipeline'), over)
    expect(over.defaultPrevented).toBe(true)
  })
})

describe('DraftCanvas / reordering records by drag', () => {
  it('moves a record within its section and writes the new order back', () => {
    const onChange = setup()
    drag(row('Teaching Assistant'), row('Research Assistant'))

    expect(placements()).toEqual(['p2', 'p1'])
    expect(onChange.mock.calls.at(-1)[0].sections[0].placements.map((item) => item.ref)).toEqual([
      'p2',
      'p1',
    ])
  })

  it('puts the records back when that drag is abandoned', () => {
    const onChange = setup()
    drag(row('Teaching Assistant'), row('Research Assistant'), { drop: false })
    expect(placements()).toEqual(['p1', 'p2'])
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('DraftCanvas / reordering from the keyboard', () => {
  it('moves a focused bullet with Alt and an arrow, which a drag cannot reach', () => {
    const onChange = setup()
    fireEvent.keyDown(row('Halved calibration time'), { key: 'ArrowUp', altKey: true })

    expect(bulletsOf('p1')).toEqual(['Halved calibration time', 'Built the DAQ pipeline'])
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('leaves the arrow keys alone without the modifier', () => {
    const onChange = setup()
    fireEvent.keyDown(row('Halved calibration time'), { key: 'ArrowUp' })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('will not push the first bullet off the top', () => {
    const onChange = setup()
    fireEvent.keyDown(row('Built the DAQ pipeline'), { key: 'ArrowUp', altKey: true })
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('DraftCanvas / dropping a record in from the bank', () => {
  it('adds it to the section it was dropped on, with its bullets copied across', () => {
    const onChange = setup({ droppingEntry: ENTRY })
    fireEvent.drop(screen.getByDisplayValue('Experience').closest('section'), { dataTransfer: transfer() })

    const added = onChange.mock.calls.at(-1)[0].sections[0].placements.at(-1)
    expect(added).toMatchObject({ entry_id: 7, title: 'Delphi', detail: 'Rust, WASM', dates: '2026 -- Present' })
    expect(added.bullets[0]).toMatchObject({ text: 'Shipped a WASM renderer', source_bullet_id: 21 })
  })

  it('copies the bullet text rather than pointing back at the bank', () => {
    // A draft that referenced the bank would silently change a resume that
    // has already been sent, the next time the bank is edited.
    const onChange = setup({ droppingEntry: ENTRY })
    fireEvent.drop(screen.getByDisplayValue('Experience').closest('section'), { dataTransfer: transfer() })
    const added = onChange.mock.calls.at(-1)[0].sections[0].placements.at(-1)
    expect(added.bullets[0].source_text).toBe('Shipped a WASM renderer')
    expect(added.bullets[0].ref).toEqual(expect.stringMatching(/^[0-9a-f]{32}$/))
  })

  it('adds it exactly once, not once per nested drop target', () => {
    const onChange = setup({ droppingEntry: ENTRY })
    fireEvent.drop(screen.getByDisplayValue('Experience').closest('section'), { dataTransfer: transfer() })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].sections[0].placements).toHaveLength(3)
  })

  it('starts the section the kind belongs in when the draft is empty', () => {
    const onChange = setup({ initial: { sections: [] }, droppingEntry: ENTRY })
    fireEvent.drop(screen.getByText(/drag a record over/i).closest('[aria-describedby]'), {
      dataTransfer: transfer(),
    })
    expect(onChange.mock.calls[0][0].sections[0]).toMatchObject({ label: 'Projects', bullet_style: 'bullets' })
  })

  it('renders a skill group as a comma-style row rather than a bullet list', () => {
    const onChange = setup({
      initial: { sections: [] },
      droppingEntry: { ...ENTRY, kind: 'skill_group', title: 'Languages' },
    })
    fireEvent.drop(screen.getByText(/drag a record over/i).closest('[aria-describedby]'), {
      dataTransfer: transfer(),
    })
    expect(onChange.mock.calls[0][0].sections[0]).toMatchObject({ label: 'Skills', bullet_style: 'inline' })
  })

  it('ignores a drop when nothing is being dragged in from the bank', () => {
    const onChange = setup()
    fireEvent.drop(screen.getByDisplayValue('Experience').closest('section'), { dataTransfer: transfer() })
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('DraftCanvas / drift from the bank', () => {
  const BANK = [{ id: 1, bullets: [{ id: 11, text: 'Rebuilt the DAQ pipeline in Rust' }, { id: 12, text: 'Halved calibration time' }] }]

  it('marks a bullet whose bank wording has moved on, and says what it now reads', () => {
    setup({ bank: BANK })
    const marker = row('Built the DAQ pipeline').querySelector('[title]')
    expect(marker).toHaveTextContent('drift')
    expect(marker).toHaveAttribute('title', 'The bank now reads: Rebuilt the DAQ pipeline in Rust')
  })

  it('leaves a bullet still matching its source unmarked', () => {
    setup({ bank: BANK })
    expect(row('Halved calibration time').textContent).not.toMatch(/drift/)
  })

  it('keeps showing the snapshot, not the bank’s newer wording', () => {
    setup({ bank: BANK })
    expect(screen.getByText('Built the DAQ pipeline')).toBeInTheDocument()
    expect(screen.queryByText('Rebuilt the DAQ pipeline in Rust')).not.toBeInTheDocument()
  })
})

describe('DraftCanvas / editing the document', () => {
  it('renames a section on blur, and not while it is still being typed', async () => {
    const user = userEvent.setup()
    const onChange = setup()
    const field = screen.getByRole('textbox', { name: /rename the experience section/i })
    await user.clear(field)
    await user.type(field, 'Research and Project Experience')
    expect(onChange).not.toHaveBeenCalled()

    await user.tab()
    expect(onChange.mock.calls[0][0].sections[0].label).toBe('Research and Project Experience')
  })

  it('does not write a section name that was only cleared', async () => {
    const user = userEvent.setup()
    const onChange = setup()
    await user.clear(screen.getByRole('textbox', { name: /rename the experience section/i }))
    await user.tab()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('takes a bullet out without disturbing the one beside it', async () => {
    const user = userEvent.setup()
    const onChange = setup()
    await user.click(screen.getByRole('button', { name: 'Remove “Built the DAQ pipeline”' }))
    expect(onChange.mock.calls[0][0].sections[0].placements[0].bullets.map((b) => b.ref)).toEqual(['b2'])
  })

  it('takes a record out of the resume without touching the bank', async () => {
    const user = userEvent.setup()
    const onChange = setup()
    await user.click(screen.getByRole('button', { name: /remove research assistant from this resume/i }))
    expect(onChange.mock.calls[0][0].sections[0].placements.map((p) => p.ref)).toEqual(['p2'])
  })

  it('adds a section to put things in', async () => {
    const user = userEvent.setup()
    const onChange = setup({ initial: { sections: [] } })
    await user.click(screen.getByRole('button', { name: /add a section/i }))
    expect(onChange.mock.calls[0][0].sections).toHaveLength(1)
  })
})

describe('DraftCanvas / jumping to a keyword', () => {
  it('scrolls the record a covered term was found in into view', () => {
    const scrollIntoView = vi.fn()
    vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(scrollIntoView)
    setup({ focusedPlacement: 'p2' })
    expect(scrollIntoView).toHaveBeenCalled()
    vi.restoreAllMocks()
  })

  it('rings the record it jumped to, so it is findable once it is on screen', () => {
    setup({ focusedPlacement: 'p2' })
    expect(document.querySelector('[data-placement="p2"]')).toHaveClass('ring-primary')
  })
})
