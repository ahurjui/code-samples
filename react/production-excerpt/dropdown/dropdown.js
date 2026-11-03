import React from 'react';
import cx from 'classnames';
import PropTypes from 'prop-types';
import { DropdownTrigger } from './dropdown-trigger';
import { DropdownContent } from './dropdown-content';

import './dropdown.scss';

export const Dropdown = props => {
  const dropdownDiv = React.useRef(null);
  const [isOpenState, setOpenState] = React.useState(props.isOpen ? props.isOpen : false);
  const classes = cx(
    'dropdown',
    { 'is-open': isOpenState },
    { [`--${props.horizontalPosition}`]: props.horizontalPosition },
    { [`--${props.verticalPosition}`]: props.verticalPosition },
    props.className
  );

  const handleTriggerClick = event => {
    const isNewOpenState = isOpenState;
    setOpenState(!isNewOpenState);

    event.preventDefault();
  };

  const handleOutsideClick = event => {
    if (event.which !== 1) return;

    if (dropdownDiv.current && event.target instanceof Node) {
      const containerContainsClick = dropdownDiv.current.contains(event.target);

      if (!containerContainsClick) {
        setOpenState(false);
      }
    }
  };

  const renderItems = () => {
    const childrenArray = React.Children.toArray(props.children);

    return childrenArray.map(child => {
      const trigger = [];
      const content = [];

      if (React.isValidElement(child)) {
        if (child.type.name === 'DropdownTrigger') {
          const state = {
            onClick: event => handleTriggerClick(event)
          };

          trigger.push(React.cloneElement(child, { ...state }));
        }

        if (child.type.name === 'DropdownContent') {
          const state = {};

          content.push(React.cloneElement(child, { ...state }));
        }

        return [trigger, content];
      }

      return null;
    });
  };

  React.useEffect(() => {
    window.addEventListener('click', handleOutsideClick);

    return () => {
      window.removeEventListener('click', handleOutsideClick);
    };
  }, []);

  return (
    <div className={classes} ref={dropdownDiv}>
      {renderItems()}
    </div>
  );
};

Dropdown.defaultProps = {
  horizontalPosition: 'right',
  verticalPosition: 'bottom'
};

Dropdown.propTypes = {
  horizontalPosition: PropTypes.oneOf(['center', 'left', 'right']),
  verticalPosition: PropTypes.oneOf(['bottom', 'center', 'top'])
};

Dropdown.Trigger = DropdownTrigger;
Dropdown.Content = DropdownContent;
