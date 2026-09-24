import { Link, Navigate, useParams } from 'react-router-dom'
import PageLayout from '../../components/PageLayout'
import { BackIcon, SettingsIcon } from '../../components/icons'
import { findSection } from './registry'
import { useSettings } from './useSettings'

/** One settings section as its own page, with a way back to the index. */
export default function SettingsSection({ onMutate }) {
  const { section: slug } = useParams()
  const section = findSection(slug)
  const state = useSettings(onMutate)

  if (!section) return <Navigate to="/settings" replace />

  const { Component } = section

  return (
    <PageLayout
      title={section.title}
      // Each section already has an icon on the Settings index; carrying it
      // onto the section's own page is what makes the two read as one place.
      icon={<SettingsIcon name={slug} className="h-6 w-6 text-on-surface-variant" />}
      description={section.description}
      error={state.error}
      actions={
        <Link to="/settings" className="btn">
          <BackIcon />
          Settings
        </Link>
      }
      banner={
        state.message ? (
          <div className="mb-4 rounded border border-primary/60 bg-primary/10 px-4 py-2 text-primary animate-fade-in">
            {state.message}
          </div>
        ) : null
      }
    >
      <div className="max-w-3xl py-6">
        <Component {...state} onMutate={onMutate} />
      </div>
    </PageLayout>
  )
}
