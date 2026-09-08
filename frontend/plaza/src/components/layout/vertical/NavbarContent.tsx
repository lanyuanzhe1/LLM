// MUI Imports
import Chip from '@mui/material/Chip'
import Typography from '@mui/material/Typography'

// Third-party Imports
import classnames from 'classnames'

// Component Imports
import NavToggle from './NavToggle'
import ModeDropdown from '@components/layout/shared/ModeDropdown'

// Util Imports
import { verticalLayoutClasses } from '@layouts/utils/layoutClasses'

const NavbarContent = () => {
  return (
    <div className={classnames(verticalLayoutClasses.navbarContent, 'flex items-center justify-between gap-4 is-full')}>
      <div className='flex items-center gap-2 sm:gap-4'>
        <NavToggle />
        <div>
          <Typography variant='h6' className='font-semibold leading-tight'>
            粮食储藏课程助手
          </Typography>
          <Typography variant='caption' color='text.secondary' className='hidden sm:block'>
            基于课程资料检索与可信引用
          </Typography>
        </div>
      </div>
      <div className='flex items-center gap-2'>
        <Chip label='本地开发' size='small' color='success' variant='tonal' />
        <ModeDropdown />
      </div>
    </div>
  )
}

export default NavbarContent
