import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ResumeAssets from './ResumeAssets'
import { api } from '../api'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    api: {
      ...actual.api,
      resumeAssets: vi.fn(),
      uploadResumeAsset: vi.fn(),
      deleteResumeAsset: vi.fn(),
    },
  }
})

const asset = (name, size = 2048) => ({ name, size, updated_at: '2026-09-23T10:00:00Z' })

async function setup({ assets = [], onInsert = vi.fn(), onChanged = vi.fn() } = {}) {
  api.resumeAssets.mockResolvedValue(assets)
  render(<ResumeAssets onInsert={onInsert} onChanged={onChanged} />)
  await waitFor(() => expect(api.resumeAssets).toHaveBeenCalled())
  return { onInsert, onChanged }
}

const file = (name, type = 'image/png') => new File(['x'], name, { type })

/** Drop onto the panel, which is how a file bypasses the input's accept list. */
const drop = (files) =>
  fireEvent.drop(screen.getByText('Assets').closest('div').parentElement, {
    dataTransfer: { files, types: ['Files'] },
  })

afterEach(() => {
  vi.clearAllMocks()
})

describe('ResumeAssets', () => {
  it('explains what the panel is for when empty', async () => {
    await setup()
    expect(await screen.findByText(/no assets/i)).toBeInTheDocument()
  })

  it('lists each asset with a human-readable size', async () => {
    await setup({ assets: [asset('seal.png', 2048), asset('headshot.jpg', 3_500_000)] })
    expect(screen.getByText('seal.png')).toBeInTheDocument()
    expect(screen.getByText('2 KB')).toBeInTheDocument()
    expect(screen.getByText('3.3 MB')).toBeInTheDocument()
  })

  it('uploads a chosen file and refreshes', async () => {
    const user = userEvent.setup()
    const { onChanged } = await setup()
    api.uploadResumeAsset.mockResolvedValue(asset('seal.png'))
    api.resumeAssets.mockResolvedValue([asset('seal.png')])

    await user.upload(screen.getByLabelText(/add/i), file('seal.png'))

    await waitFor(() => expect(api.uploadResumeAsset).toHaveBeenCalled())
    expect(await screen.findByText('seal.png')).toBeInTheDocument()
    // A new image changes what the document can resolve, so the render on
    // screen is stale until it is rebuilt.
    expect(onChanged).toHaveBeenCalled()
  })

  it('accepts files dropped onto the panel', async () => {
    const { onChanged } = await setup()
    api.uploadResumeAsset.mockResolvedValue(asset('seal.png'))
    api.resumeAssets.mockResolvedValue([asset('seal.png')])

    drop([file('seal.png')])

    await waitFor(() => expect(api.uploadResumeAsset).toHaveBeenCalled())
    expect(await screen.findByText('seal.png')).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
  })

  it('reports a rejected file by name and keeps the valid ones', async () => {
    // Dropped rather than picked: the file input carries an `accept` list, so
    // the picker never offers a .sh in the first place. A drop bypasses that,
    // which makes it the path where the server's rejection actually shows up.
    await setup()
    api.uploadResumeAsset
      .mockRejectedValueOnce(new Error("'.sh' is not a supported asset."))
      .mockResolvedValueOnce(asset('seal.png'))
    api.resumeAssets.mockResolvedValue([asset('seal.png')])

    drop([file('evil.sh'), file('seal.png')])

    expect(await screen.findByText(/evil\.sh: .*not a supported asset/)).toBeInTheDocument()
    // The bad file must not take the good one down with it.
    expect(api.uploadResumeAsset).toHaveBeenCalledTimes(2)
    expect(await screen.findByText('seal.png')).toBeInTheDocument()
  })

  it('deletes an asset', async () => {
    const user = userEvent.setup()
    const { onChanged } = await setup({ assets: [asset('seal.png')] })
    api.deleteResumeAsset.mockResolvedValue(null)
    api.resumeAssets.mockResolvedValue([])

    await user.click(screen.getByRole('button', { name: 'Delete seal.png' }))

    await waitFor(() => expect(api.deleteResumeAsset).toHaveBeenCalledWith('seal.png'))
    expect(onChanged).toHaveBeenCalled()
  })

  it('surfaces a failed delete rather than silently keeping the row', async () => {
    const user = userEvent.setup()
    await setup({ assets: [asset('seal.png')] })
    api.deleteResumeAsset.mockRejectedValue(new Error('No asset called seal.png'))

    await user.click(screen.getByRole('button', { name: 'Delete seal.png' }))

    expect(await screen.findByText(/No asset called seal\.png/)).toBeInTheDocument()
  })
})

describe('ResumeAssets / inserting into the source', () => {
  it.each([
    ['seal.png', '\\includegraphics[width=1in]{seal.png}'],
    ['photo.JPG', '\\includegraphics[width=1in]{photo.JPG}'],
    ['section.tex', '\\input{section}'],
    ['awesome.sty', '\\usepackage{awesome}'],
    ['refs.bib', '\\bibliography{refs}'],
  ])('writes the right command for %s', async (name, expected) => {
    const user = userEvent.setup()
    const { onInsert } = await setup({ assets: [asset(name)] })
    await user.click(screen.getByRole('button', { name: `Insert ${name}` }))
    expect(onInsert).toHaveBeenCalledWith(expected)
  })

  it('falls back to the bare name for anything else', async () => {
    const user = userEvent.setup()
    const { onInsert } = await setup({ assets: [asset('diagram.pdf')] })
    await user.click(screen.getByRole('button', { name: 'Insert diagram.pdf' }))
    expect(onInsert).toHaveBeenCalledWith('diagram.pdf')
  })
})
