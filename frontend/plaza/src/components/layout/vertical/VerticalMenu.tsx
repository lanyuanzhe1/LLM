'use client'

import { useTheme } from '@mui/material/styles'
import PerfectScrollbar from 'react-perfect-scrollbar'

import { Menu, MenuItem, MenuSection } from '@menu/vertical-menu'
import useVerticalNav from '@menu/hooks/useVerticalNav'

import menuItemStyles from '@core/styles/vertical/menuItemStyles'
import menuSectionStyles from '@core/styles/vertical/menuSectionStyles'

const VerticalMenu = ({ scrollMenu }: { scrollMenu: (container: any, isPerfectScrollbar: boolean) => void }) => {
  const theme = useTheme()
  const { isBreakpointReached } = useVerticalNav()
  const ScrollWrapper = isBreakpointReached ? 'div' : PerfectScrollbar

  return (
    <ScrollWrapper
      {...(isBreakpointReached
        ? {
            className: 'bs-full overflow-y-auto overflow-x-hidden',
            onScroll: container => scrollMenu(container, false)
          }
        : {
            options: { wheelPropagation: false, suppressScrollX: true },
            onScrollY: container => scrollMenu(container, true)
          })}
    >
      <Menu menuItemStyles={menuItemStyles(theme)} menuSectionStyles={menuSectionStyles(theme)}>
        <MenuItem href='/' icon={<i className='ri-dashboard-line' />}>
          学习工作台
        </MenuItem>
        <MenuItem href='/chat' icon={<i className='ri-sparkling-2-line' />}>
          智能问答
        </MenuItem>

        <MenuSection label='课程工具'>
          <MenuItem href='/knowledge' icon={<i className='ri-book-open-line' />}>
            课程资料
          </MenuItem>
          <MenuItem href='/cases' icon={<i className='ri-pulse-line' />}>
            储粮案例分析
          </MenuItem>
        </MenuSection>

        <MenuSection label='学习任务'>
          <MenuItem
            href='/chat?prompt=请结合课程资料讲解低温储粮的核心概念、作用机制、适用条件和易错点。'
            icon={<i className='ri-lightbulb-flash-line' />}
          >
            概念讲解
          </MenuItem>
          <MenuItem
            href='/chat?prompt=请基于课程资料总结低温储粮的关键知识点，并给出复习提纲。'
            icon={<i className='ri-file-list-3-line' />}
          >
            课程总结
          </MenuItem>
          <MenuItem
            href='/chat?prompt=请基于课程资料生成3道由易到难的练习题，先只展示第1道且不要公布答案。'
            icon={<i className='ri-question-answer-line' />}
          >
            生成练习
          </MenuItem>
          <MenuItem
            href='/chat?prompt=我想在7天内复习粮食储藏课程，请先询问我的基础和每天可用时间。'
            icon={<i className='ri-calendar-schedule-line' />}
          >
            学习规划
          </MenuItem>
        </MenuSection>
      </Menu>
    </ScrollWrapper>
  )
}

export default VerticalMenu
