// @vitest-environment jsdom

import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import PagesDemo from './PagesDemo'

it('标识演示限制并允许切换合成示例页面', () => {
  render(<PagesDemo />)
  expect(screen.getByText(/合成示例/)).toBeTruthy()
  expect(screen.getByText(/未连接后端/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /脚本审核/ }))
  expect(screen.getByRole('heading', { name: '脚本审核' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /图片工作区/ }))
  expect(screen.getByRole('heading', { name: '图片工作区' })).toBeTruthy()
})
