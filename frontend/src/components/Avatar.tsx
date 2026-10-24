import clsx from 'clsx'
import { useState } from 'react'
import { avatarUrl } from '../lib/api'
import { avatarGradient, initials } from '../lib/format'

export function Avatar({
  id,
  name,
  photoId,
  size = 36,
  square,
}: {
  id: number
  name: string
  photoId?: string | number | null
  size?: number
  square?: boolean
}) {
  const [failed, setFailed] = useState(false)
  const src = !failed ? avatarUrl(photoId == null ? null : String(photoId)) : undefined
  return (
    <span
      className={clsx(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden font-semibold text-white select-none',
        square ? 'rounded-[28%]' : 'rounded-full',
      )}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.38), background: avatarGradient(id) }}
      aria-hidden
    >
      {initials(name)}
      {src && (
        <img
          src={src}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className="absolute inset-0 size-full object-cover"
        />
      )}
    </span>
  )
}
