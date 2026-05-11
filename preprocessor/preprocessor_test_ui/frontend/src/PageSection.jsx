import React from 'react';
import { Box, Paper, Stack, Typography } from '@mui/material';
import { panelSx } from './adminTheme';

function PageSection({ title, description, actions, children, sx }) {
  return (
    <Paper sx={{ ...panelSx, ...sx }}>
      {(title || description || actions) && (
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', sm: 'center' }}
          spacing={1.25}
          sx={{ mb: 2 }}
        >
          <Box>
            {title && <Typography variant="h6">{title}</Typography>}
            {description && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {description}
              </Typography>
            )}
          </Box>
          {actions}
        </Stack>
      )}
      {children}
    </Paper>
  );
}

export default PageSection;
